"""R4 and P0.9: real local streaming, deterministic tokenizer fixtures, and mocked orchestration."""
import asyncio
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prefix_sched as client
import make_wmp_prompts as builder
import kx_006
import summarize_006 as summary
import finalize_006


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False): return text.split()
    def decode(self, ids): return ' '.join(ids)
    def apply_chat_template(self, messages, **_): return self.encode(' '.join(m['content'] for m in messages))


class BuilderTests(unittest.TestCase):
    def test_percentiles_missing_fallback_and_shares(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'usage.jsonl'
            values=[1024,2048,4096,8192,16384]
            log.write_text(''.join(json.dumps(dict(event='response',tokens_cached=n))+'\n' for n in values))
            lengths, method=builder.prefix_lengths([log])
            self.assertEqual(lengths,[2048,4096,8192,14848]);self.assertFalse(method['fallback'])
            log.write_text(log.read_text()+json.dumps(dict(event='response',tokens_cached=None))+'\n')
            self.assertEqual(builder.prefix_lengths([log])[0],builder.FALLBACK)
            self.assertTrue(builder.prefix_lengths([])[1]['fallback'])
            self.assertEqual(builder.counts(256),[102,77,51,26])
            self.assertEqual(builder.counts(128),[51,38,26,13])

    def test_builder_full_fixed_splits_hashes_unique_suffixes_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';base=atlas/'tasks/c01/base';base.mkdir(parents=True)
            (atlas/'tasks/FROZEN.json').write_text(json.dumps(dict(tasks=[dict(id='c01')])))
            (atlas/'tasks/c01/task.yaml').write_text('base: base\n')
            (base/'code.py').write_text(' '.join(f'code_{i}' for i in range(460000)))
            (base/'tests').mkdir();(base/'tests/test_hidden.py').write_text('never select this hidden test')
            a=builder.build(FakeTokenizer(),atlas,root/'a')
            b=builder.build(FakeTokenizer(),atlas,root/'b')
            self.assertEqual(a,b)
            seen=set();ranges=[]
            for file,n in [('wmp-256.jsonl',256),('wmp-128.jsonl',128),('kx-0.jsonl',8)]:
                raw=(root/'a'/file).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),a['files_sha256'][file])
                self.assertEqual(raw,(root/'b'/file).read_bytes())
                rows=[json.loads(line) for line in raw.splitlines()]
                self.assertEqual(len(rows),n)
                for row in rows:
                    self.assertNotIn(row['request_id'],seen);seen.add(row['request_id']);ranges.append(row['source_range'])
                    self.assertTrue(992<=row['suffix_tokens']<=1056)
                    self.assertEqual(row['messages'][0]['content'],(root/'a'/f'prefix_{row["group"]}.txt').read_text())
            self.assertEqual(len(seen),392)
            ranges.sort();self.assertTrue(all(a[1]<=b[0] for a,b in zip(ranges,ranges[1:])))
            self.assertEqual([g['prefix_tokens'] for g in a['groups'].values()],builder.FALLBACK)
            self.assertTrue(all('tests/' not in f['path'] for f in a['source_files']))


class StreamingTests(unittest.TestCase):
    def test_fake_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'check';client.self_test(out)
            rows=[json.loads(line) for line in (out/'fake-run/requests.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),40);self.assertTrue(all(r['group'] in client.GROUPS for r in rows))
            self.assertTrue(all(r['ttft_s']<=r['e2e_s'] and r['output_tokens']==2 for r in rows))

    def test_summary_math_and_missing_cached_usage(self):
        rows=[dict(group='G1',ttft_s=1,cached_tokens=10,prompt_tokens=100,status='ok',output_tokens=2),
              dict(group='G1',ttft_s=3,cached_tokens=10,prompt_tokens=300,status='ok',output_tokens=6)]
        metrics=[dict(name='sglang:cache_hit_rate',type='gauge',value=.2),dict(name='sglang:cache_hit_rate',type='gauge',value=.6)]
        s=client.summarize(rows,2,metrics)
        self.assertEqual(s['groups']['G1']['ttft_p50_s'],2)
        self.assertAlmostEqual(s['groups']['G1']['ttft_p95_s'],2.9)
        self.assertEqual(s['groups']['G1']['hit_rate'],.05)
        self.assertEqual(s['output_tok_per_s'],4);self.assertEqual(s['request_throughput'],1)
        self.assertAlmostEqual(s['overall_metric_delta'],.4)
        rows[0]['cached_tokens']=None
        self.assertIsNone(client.summarize(rows,2,metrics)['groups']['G1']['hit_rate'])

    def test_failed_request_keeps_group(self):
        async def scenario():
            async def broken(*a,**k):
                raise ValueError('fake transport failure')
                yield b''
            with patch.object(client,'http_stream',broken):
                return await client.request('http://127.0.0.1:1/v1',dict(request_id='err',group='G4',messages=[]),'fake',1)
        row=asyncio.run(scenario())
        self.assertEqual(row['group'],'G4');self.assertEqual(row['status'],'error');self.assertIsNone(row['cached_tokens'])


class R4Tests(unittest.TestCase):
    def test_live_summary_does_not_wait_for_claim_and_final_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'runs.json'
            data=json.loads((ROOT/'inputs/atlas-dry-p08/runs.json').read_text())
            data['rows']=[r for r in data['rows'] if r['level']=='c4']
            for r in data['rows']:
                r.update(grading_pending=True,solved_by_tests=r['tests_passed'] and not r['tamper'],claim=None)
            data['complete']=False;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                summary.summarize([path],allow_fixtures=True)
            s,rows=summary.summarize([path],allow_fixtures=True,allow_pending=True)
            self.assertEqual(s[0]['runs'],3);self.assertEqual(s[0]['solved'],1);self.assertEqual(s[0]['pending_mac_grades'],3)

    def test_offline_finalization_after_host_is_gone(self):
        self.exercise_finalization(False)

    def test_offline_rehearsal_finalization_after_host_is_gone(self):
        self.exercise_finalization(True)

    def exercise_finalization(self, rehearsal):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'live.json'
            row=json.loads((ROOT/'inputs/atlas-dry-p08/runs.json').read_text())['rows'][0]
            row.update(config='qwen38-27b-mi300x',model='Qwen/Qwen3.8-27B',fixture=False,scored=True,grading_pending=True,
                       solved_by_tests=True,tests_passed=True,tamper=False,category='solved',end_reason='completed',claim=None)
            row.update(fixture=rehearsal,scored=not rehearsal,rehearsal=rehearsal)
            scope=root/('results/rehearsal' if rehearsal else 'results')
            report=dict(rehearsal=rehearsal,atlas_commit=summary.PIN,complete=False,execution_complete=True,rows=[row],pending_mac_grades=1)
            p.write_text(json.dumps(report));run=row['run_id']
            pending=scope/'grading/pending'/run;pending.mkdir(parents=True)
            native=pending/'native-tests';native.mkdir();(native/'tests.json').write_text('{}')
            request=dict(run_id=run,atlas_commit=summary.PIN,native_tests_sha256=hashlib.sha256(b'{}').hexdigest(),record=dict(tests=dict(testsPassed=True),protection=dict(tamper=False)))
            raw=json.dumps(request).encode();(pending/'request.json').write_bytes(raw)
            with self.assertRaises(OSError):finalize_006.finalize([p],root,rehearsal=rehearsal)
            self.assertFalse((root/'results/summary.csv').exists())
            returned=scope/'grading/returned'/run;returned.mkdir(parents=True)
            (returned/'response.json').write_text(json.dumps(dict(request_sha256=hashlib.sha256(raw).hexdigest(),run_id=run,atlas_commit=summary.PIN,
                claim=dict(source='llm_fallback',audited=True,claim='done'),category='solved')))
            (returned/'audit.json').write_text(json.dumps(dict(accepted=True,expected='done',reported='done',reviewer='test',reason='fake audit')))
            self.assertEqual(finalize_006.finalize([p],root,rehearsal=rehearsal),1)
            self.assertTrue((scope/'summary.csv').exists())
            if rehearsal:self.assertFalse((root/'results/summary.csv').exists())


class KxTests(unittest.TestCase):
    def fixture(self, root):
        (root/'notes').mkdir();(root/'results/live').mkdir(parents=True);(root/'logs').mkdir()
        (root/'STATE.json').write_text(json.dumps(dict(steps={s:dict(status='DONE') for s in ('P0.8','P0.9','P3')})))
        (root/'notes/budget_check.json').write_text(json.dumps(dict(projected_without_5b_gpu_hours=7.5)))
        (root/'logs/current_server.json').write_text(json.dumps(dict(engine='vllm',model_revision='fixed')))
        with (root/'results/live/summary.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=['level','runs']);w.writeheader()
            for c in (1,4,8,16):w.writerow(dict(level=f'c{c}',runs=60 if c==16 else 30))
        now=datetime.now(timezone.utc)
        return dict(CREATED_AT=(now-timedelta(hours=1)).isoformat(),HARD_DEADLINE=(now+timedelta(hours=8)).isoformat(),SESSION_CAP_HOURS='9',SGLANG_IMAGE='fake@sha256:pin',KX_SKIP='0')

    def test_fresh_policy_only_runs_and_kx0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=self.fixture(root);calls=[]
            def fake(args,**kwargs):
                calls.append(args)
                if args[0]=='docker':
                    out=root/'results/raw/Kx/prompts';out.mkdir()
                    for name in ('kx-0.jsonl','wmp-256.jsonl','wmp-128.jsonl'):(out/name).write_text('fake')
                if 'prefix_sched.py' in str(args):
                    name=args[args.index('--run-id')+1];out=Path(args[args.index('--output-dir')+1]);out.mkdir(parents=True)
                    check=name=='Kx-0';n=8 if check else 128 if name.endswith('c8') else 256
                    groups={g:dict(requests=2 if check else builder.counts(n)[i],failed=0,hit_rate=.5,ttft_p50_s=1,ttft_p95_s=2) for i,g in enumerate(client.GROUPS)}
                    result=dict(run_id=name,concurrency=int(args[args.index('--concurrency')+1]),ok=n,groups=groups,cache_metric_name='sglang:cache_hit_rate',cache_metric_type='gauge',cache_metric_changed=True,
                                overall_metric_delta=.5,overall_usage_hit_rate=.5,output_tok_per_s=10,request_throughput=1)
                    (out/'summary.json').write_text(json.dumps(result))
                return subprocess.CompletedProcess(args,0)
            with patch.dict(os.environ,env),patch.object(kx_006.subprocess,'run',fake):kx_006.run(root)
            servers=[a[-1] for a in calls if '_kx-serve' in a]
            self.assertEqual(servers,['fcfs','lpm','fcfs','lpm','fcfs','lpm'])
            clients=[a for a in calls if 'prefix_sched.py' in str(a)]
            self.assertEqual([a[a.index('--run-id')+1] for a in clients],['Kx-0','Kx-FCFS-c16','Kx-LPM-c16','Kx-FCFS-c8','Kx-LPM-c8'])
            self.assertEqual(clients[1][clients[1].index('--prompts')+1],clients[2][clients[2].index('--prompts')+1])
            self.assertIn('@thewidechaos',(root/'notes/kx_report.md').read_text())

    def test_drop_rules_no_engine_or_client_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=self.fixture(root)
            with patch.dict(os.environ,env):
                self.assertIsNone(kx_006.drop_reason(root))
                (root/'notes/budget_check.json').write_text(json.dumps(dict(projected_without_5b_gpu_hours=9.6)))
                self.assertIn('above 9.5',kx_006.drop_reason(root))
                with patch.object(kx_006.subprocess,'run') as commands:kx_006.run(root);commands.assert_not_called()
                self.assertIn('above 9.5',(root/'notes/friction.md').read_text())

    def test_explicit_skip_deadline_and_partial_c32(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=self.fixture(root)
            with patch.dict(os.environ,env):
                with patch.dict(os.environ,{'KX_SKIP':'1'}):self.assertIn('dippo',kx_006.drop_reason(root))
                with patch.dict(os.environ,{'HARD_DEADLINE':(datetime.now(timezone.utc)+timedelta(minutes=59)).isoformat()}):self.assertIn('60 minutes',kx_006.drop_reason(root))
                with (root/'results/live/summary.csv').open('a') as f:f.write('c32,1\n')
                self.assertIn('c32',kx_006.drop_reason(root))

    def test_kx0_failure_skips_all_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=self.fixture(root);clients=[]
            def fake(args,**kwargs):
                if args[0]=='docker':(root/'results/raw/Kx/prompts').mkdir()
                if 'prefix_sched.py' in str(args):
                    clients.append(args[args.index('--run-id')+1]);out=Path(args[args.index('--output-dir')+1]);out.mkdir()
                    (out/'summary.json').write_text(json.dumps(dict(ok=8,groups={g:dict(requests=2) for g in client.GROUPS},cache_metric_name=None,cache_metric_changed=False)))
                return subprocess.CompletedProcess(args,0)
            with patch.dict(os.environ,env),patch.object(kx_006.subprocess,'run',fake):kx_006.run(root)
            self.assertEqual(clients,['Kx-0'])
            self.assertIn('Kx-0',(root/'notes/friction.md').read_text())
            self.assertEqual(json.loads((root/'STATE.json').read_text())['steps']['P3b']['status'],'BLOCKED')


class LiveExporterTests(unittest.TestCase):
    def test_actual_exporter_continues_missing_claims_and_blocks_only_final(self):
        self.exercise_exporter(False)

    def test_rehearsal_exporter_uses_same_pending_flow_in_own_results(self):
        self.exercise_exporter(True)

    def exercise_exporter(self, rehearsal):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);study=root/'study';scripts=study/'scripts';scripts.mkdir(parents=True);atlas=root/'atlas';atlas.mkdir()
            for name in ('atlas_export_006.ts','export_support_006.ts','atlas_mac_grade_006.ts','summarize_006.py','ttft_006.py'):
                shutil.copyfile(ROOT/'scripts'/name,scripts/name)
            scope=study/('results/rehearsal' if rehearsal else 'results')
            manifest=dict(study=dict(level='c4',dryRun=rehearsal),localCost=dict(hourlyRateUsd=1.99),id='live-rehearsal-c4' if rehearsal else 'live-c4')
            rows={};specs=[]
            for i in (1,2):
                run=f'c{i:02d}__qwen38-27b-mi300x__a2';specs.append(dict(runId=run))
                trace=root/f'{i}.json';trace.write_text('{}')
                row=dict(run_id=run,state='finished',trace_path=str(trace),task_id=f'c{i:02d}',end_reason='completed',backend='local',harness='opencode',model='Qwen/Qwen3.8-27B',
                    config_id='qwen38-27b-mi300x',harness_version='1.19.0',started_at='2026-10-15T00:00:00Z',ended_at='2026-10-15T00:00:01Z',wall_s=1,config_json='{}',limits_json='null')
                rows[run]=row
                pending=scope/'grading/pending'/run;(pending/'native-tests').mkdir(parents=True);(pending/'native-tests/tests.json').write_text('{}')
                evidence=dict(finalMessage='No status line',tokens=dict(input=100,output=10,cached=80),toolCalls=[dict(name='tool')],raw=[dict(event='response',inference_s=.1)],inferenceS=.1,tokenSource='proxy')
                request=dict(version=1,atlas_commit=summary.PIN,run_id=run,level='c4',trace_sha256=hashlib.sha256(b'{}').hexdigest(),workspace_sha256='workspace',native_tests_sha256=hashlib.sha256(b'{}').hexdigest(),work=True,
                    record=dict(runId=run,executionRow=row,evidence=evidence,tests=dict(testsPassed=i==1),protection=dict(tamper=False),cost=dict(costUsd=0),flags=[],claim=None,status='audit_pending'))
                (pending/'request.json').write_text(json.dumps(request))
            modules={
                'runner/manifest.ts':f'export const loadManifest=async()=>({{manifest:{json.dumps(manifest)},runs:{json.dumps(specs)}}});',
                'runner/store.ts':f'const rows={json.dumps(rows)};export class Store{{db={{prepare:q=>({{get:id=>q.includes("manifest_json")?{{manifest_json:{json.dumps(json.dumps(manifest))}}}:undefined}})}};row(id){{return rows[id];}}acquire(){{return "fake";}}release(){{}}close(){{}}}}',
                'grading/service.ts':'export const gradeRun=async()=>{throw Error("Forbidden classifier path");};',
                'grading/claim.ts':'export const parseStatus=()=>null;',
                'grading/evidence.ts':"import{readFile}from'node:fs/promises';export const artifactText=async p=>readFile(p,'utf8');export const readEvidence=async()=>({finalMessage:'No STATUS'});",
                'grading/grader.ts':'export const gradeTests=()=>{throw Error("No Docker");};',
                'grading/task.ts':'export const gradingTask=()=>{};',
                'grading/tree.ts':"export const treeHash=async()=> 'workspace';",
                'grading/tamper.ts':'export const captureProtection=()=>{},compareProtection=()=>{};',
                'runner/host/images.ts':'export const recheckRuntime=()=>{};',
                'grading/cost.ts':'export const readPrices=()=>{},computeCost=()=>{};',
                'grading/taxonomy.ts':"export const observedAgentWork=()=>{},secondaryFlags=()=>{};export const categorize=x=>x.testsPassed?'solved':'no_claim';",
                'grading/cutoff.ts':'export const taskProvenance=()=>{};',
                'grading/redact.ts':'export const redact=x=>x;',
            }
            for path,text in modules.items():
                p=atlas/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            bin=root/'bin';bin.mkdir();git=bin/'git';git.write_text('#!/bin/sh\necho '+summary.PIN+'\n');git.chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],REHEARSAL='1' if rehearsal else '0');db=atlas/'data/campaign/atlas.db'
            cmd=['node',str(scripts/'atlas_export_006.ts'),'manifest.json',str(db)]
            r=subprocess.run(cmd,cwd=atlas,env=env,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            report=json.loads((db.parent/'live/c4/runs.json').read_text())
            self.assertEqual(report['pending_mac_grades'],2);self.assertEqual(len(report['rows']),2)
            with (scope/'live/summary.csv').open() as f:s=next(csv.DictReader(f))
            if rehearsal:
                self.assertTrue(report['rehearsal']);self.assertTrue(all(r['fixture'] and not r['scored'] for r in report['rows']))
                self.assertFalse((study/'results/live').exists());self.assertFalse((study/'results/grading').exists())
            self.assertEqual(json.loads((scope/'grading/counts/c4.json').read_text())['pending_mac_grades'],2)
            self.assertEqual(s['solved'],'1');self.assertEqual(s['pending_mac_grades'],'2')
            self.assertFalse((study/'results/summary.csv').exists())
            r=subprocess.run(cmd+['--final'],cwd=atlas,env=env,capture_output=True,text=True)
            self.assertEqual(r.returncode,3,r.stderr);self.assertFalse((study/'results/summary.csv').exists())

if __name__=='__main__':unittest.main()
