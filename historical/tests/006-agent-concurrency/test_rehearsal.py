"""CPU rehearsal: real SSE/client/parser/metrics, isolated exports and native inputs."""
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import fake_engine_006 as fake
import rehearsal_006 as rehearsal
import probe_006
import gpu_sampler
import prefix_sched
import make_wmp_prompts as builder
import finalize_006
from ttft_006 import histogram, level_ttft
from test_p09 import FakeTokenizer
import kx_006


class StreamingTests(unittest.TestCase):
    def test_both_personalities_actual_sse_tool_round_trip_and_metrics(self):
        for engine in ('vllm','sglang'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                server = fake.Server(('127.0.0.1',0),engine)
                thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                try:
                    def metrics():
                        with urllib.request.urlopen(base+'/metrics') as r:return r.read().decode()
                    with urllib.request.urlopen(base+'/v1/models') as r:self.assertEqual(json.load(r)['data'][0]['id'],fake.MODEL)
                    before=histogram(metrics(),engine)
                    body=dict(model=fake.MODEL,stream=True,messages=[dict(role='user',content='check')],
                              tools=[dict(type='function',function=dict(name='bash',parameters=dict(type='object')))])
                    req=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(req) as r:first=r.read().decode()
                    events=[json.loads(line[6:]) for line in first.splitlines() if line.startswith('data: {')]
                    self.assertEqual(events[-1]['usage']['prompt_tokens_details']['cached_tokens'],0)
                    call=next(c for e in events for c in e.get('choices',[]) if c['delta'].get('tool_calls'))['delta']['tool_calls'][0]
                    self.assertEqual(call['function']['name'],'bash')
                    self.assertEqual(json.loads(call['function']['arguments'])['command'],'pwd')
                    body['messages'] += [dict(role='assistant',tool_calls=[call]),dict(role='tool',tool_call_id=call['id'],content='/workspace')]
                    req=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(req) as r:second=r.read().decode()
                    self.assertIn('reasoning_content',second);self.assertNotIn('STATUS:',second)
                    self.assertIn('"cached_tokens": 2048',second)
                    after=histogram(metrics(),engine)
                    delta=level_ttft([dict(ts=0,level='c8',boundary='before',engine_ttft_histogram=before),
                                      dict(ts=1,level='c8',boundary='after',engine_ttft_histogram=after)],'c8')
                    self.assertEqual(delta['engine_ttft_observations'],2)
                    self.assertEqual(delta['engine_ttft_status'],'ok')
                    # Feed the *actual* fake-server response into the pinned production parser.
                    atlas=Path(os.environ.get('ATLAS_SOURCE','<WORKDIR>/lab/atlas'))
                    if not (atlas/'proxy/gateway.ts').exists():self.fail('Pinned ATLAS source required for parser integration')
                    parser=Path(tmp)/'parse.mts'
                    parser.write_text(f"import{{parseEvidence}}from{json.dumps(str(atlas/'proxy/gateway.ts'))};const r=parseEvidence('/v1/chat/completions',{json.dumps(second)},true);if(r.usage?.cached!==2048||r.usage?.output!==16)throw Error(JSON.stringify(r));console.log(JSON.stringify(r.usage));")
                    r=subprocess.run(['node',str(parser)],capture_output=True,text=True)
                    self.assertEqual(r.returncode,0,r.stderr)
                    prompts=Path(tmp)/'prompts.jsonl'
                    prompts.write_text(''.join(json.dumps(dict(request_id=str(i),group=f'G{i%4+1}',messages=[dict(role='user',content='check')]))+'\n' for i in range(8)))
                    with patch.dict(os.environ,REHEARSAL='1'):
                        result=asyncio.run(prefix_sched.run(prompts,Path(tmp)/'run',4,'check',base+'/v1',settle=0))
                    self.assertEqual(result['ok'],8);self.assertTrue(result['rehearsal'])
                    self.assertTrue(all(g['requests']==2 and g['failed']==0 and g['ttft_p95_s']>0 for g in result['groups'].values()))
                finally:
                    server.shutdown();server.server_close();thread.join()

    def test_sampler_null_gpu_and_real_histogram(self):
        raw=b'vllm:time_to_first_token_seconds_bucket{le="1"} 1\nvllm:time_to_first_token_seconds_bucket{le="+Inf"} 1\nvllm:gpu_cache_usage_perc 0.9\nvllm:num_preemptions_total 3\n'
        import io
        with patch.dict(os.environ,REHEARSAL='1'), patch('urllib.request.urlopen',return_value=io.BytesIO(raw)), patch('subprocess.run',side_effect=AssertionError('GPU subprocess forbidden')):
            result=gpu_sampler.sample('vllm')
        for key in ('peak_vram_mb','kv_usage','preemptions'):self.assertIsNone(result[key])
        self.assertIsNotNone(result['engine_ttft_histogram']);self.assertTrue(result['rehearsal'])


class NativeInputTests(unittest.TestCase):
    def test_short_native_manifests_and_unchanged_production_order(self):
        source=Path(os.environ.get('ATLAS_SOURCE','<WORKDIR>/lab/atlas'))
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,REHEARSAL='1'):
            atlas=Path(tmp)/'atlas';dest=atlas/'campaigns/rocm-recipes-006/manifests';dest.mkdir(parents=True)
            for c in (1,4,8,16):shutil.copy(source/f'campaigns/rocm-recipes-006/manifests/c{c}.json',dest)
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('*')}
            rehearsal.prepare(atlas);selected=probe_006.prepare(atlas)
            self.assertEqual(len(selected),8);self.assertTrue(probe_006.REQUIRED<=set(selected))
            for p in (atlas/'data/rocm-recipes-006-rehearsal').glob('c*.json'):
                m=json.loads(p.read_text());original=json.loads((dest/p.name).read_text())
                self.assertEqual(m['mode'],'native');self.assertTrue(m['study']['dryRun']);self.assertEqual(len(m['runs']),2)
                for key in ('proxyProfiles','taskSet','budgets','perRunS'):self.assertEqual(m[key],original[key])
                self.assertEqual(m['runs'][0]['task'],original['runs'][0]['task'])
            for engine in ('vllm','sglang'):
                for stage,n in [('smoke',1),('c8',8)]:
                    m=json.loads((atlas/f'data/rocm-recipes-006-rehearsal-probe/{engine}-{stage}.json').read_text())
                    self.assertEqual(len(m['runs']),n);self.assertEqual(m['mode'],'native')
            validator=Path(tmp)/'validate.mts'
            validator.write_text('import{loadManifest}from '+json.dumps(str(source/'runner/manifest.ts'))+';for(const p of process.argv.slice(2)){const m=await loadManifest(p);if(m.manifest.mode!=="native")throw Error("Not native");console.log(m.runs.length);}')
            manifests=sorted((atlas/'data').rglob('*.json'))
            result=subprocess.run(['node',str(validator),*map(str,manifests)],cwd=source,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(result.stdout.splitlines()),8)
            self.assertEqual(hashes,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('*')})

    def test_builder_short_shares_and_hashed_seeded_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';base=atlas/'tasks/c01/base';base.mkdir(parents=True)
            (atlas/'tasks/FROZEN.json').write_text(json.dumps(dict(tasks=[dict(id='c01')])))
            (atlas/'tasks/c01/task.yaml').write_text('base: base\n')
            (base/'code.py').write_text(' '.join(f'code_{i}' for i in range(100000)))
            a=builder.build(FakeTokenizer(),atlas,root/'a',rehearsal=True)
            b=builder.build(FakeTokenizer(),atlas,root/'b',rehearsal=True)
            self.assertEqual(a,b);self.assertTrue(a['fixture']);self.assertTrue(a['rehearsal'])
            self.assertEqual(a['splits']['wmp-20.jsonl']['group_counts'],dict(zip(builder.ROLES,[8,6,4,2])))
            self.assertEqual(a['splits']['kx-0.jsonl']['requests'],8)
            for name,digest in a['files_sha256'].items():self.assertEqual(hashlib.sha256((root/'a'/name).read_bytes()).hexdigest(),digest)

    def test_root_handoff_repair_precedes_runuser_and_kx_maps_user(self):
        source=(ROOT/'scripts/atlas_remote.sh').read_text()
        start=source.index('    if [[ $(id -u) == 0 ]]; then')
        handoff=source[start:source.index("    [[ $(id -un)",start)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir();bin=root/'bin';bin.mkdir();calls=root/'calls'
            # Replace only path validation, to exercise the real repair helper in a temp tree.
            helper=(ROOT/'scripts/atlas_ownership_006.sh').read_text().replace('^<HOME>/[A-Za-z0-9_-]+$','^/[A-Za-z0-9_/-]+$')
            (root/'scripts/atlas_ownership_006.sh').write_text(helper)
            db=root/'atlas/data/probe/c8.db';db.parent.mkdir(parents=True);db.touch();db.chmod(0o600)
            for name,body in [('id','echo 0'),('chown','echo repair >> "$CALLS"'),('runuser','echo handoff >> "$CALLS"; chmod 600 "$DB"; test -w "$DB"')]:
                p=bin/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            result=subprocess.run(['bash','-eu'],input=handoff,env=dict(os.environ,ROOT_DIR=tmp,REHEARSAL='0',SESSION4='0',action='probe',PATH=str(bin)+':'+os.environ['PATH'],CALLS=str(calls),DB=str(db)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls.read_text().splitlines(),['repair','handoff'])
            self.assertEqual(db.stat().st_mode&0o777,0o600)
        kx=(ROOT/'scripts/kx_006.py').read_text()
        self.assertIn("'--user', user",kx);self.assertIn("f'{hf}:/hf:ro'",kx);self.assertNotIn('<HOME>/.cache/huggingface',kx)


class IsolationTests(unittest.TestCase):
    def test_short_kx_uses_same_orchestrator_and_uid_for_every_container(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,REHEARSAL='1',KX_SKIP='0',SGLANG_IMAGE='pinned-fixture'):
            root=Path(tmp);scope=root/'results/rehearsal'
            (scope/'notes').mkdir(parents=True);(scope/'logs').mkdir();(scope/'live').mkdir()
            (scope/'STATE.json').write_text(json.dumps(dict(steps={})))
            (scope/'logs/current_server.json').write_text(json.dumps(dict(engine='vllm',model_revision=rehearsal.TOKENIZER_REVISION)))
            with (scope/'live/summary.csv').open('w') as f:
                f.write('level,runs\n');f.writelines(f'c{c},2\n' for c in (1,4,8,16))
            for c in (1,4,8,16):
                p=scope/f'atlas/main/live/c{c}/runs.json';p.parent.mkdir(parents=True)
                p.write_text(json.dumps(dict(rehearsal=True,execution_complete=True,rows=[{},{}])))
            calls=[]
            def command(args,**kwargs):
                calls.append(args)
                if '/scripts/make_wmp_prompts.py' in args:
                    out=scope/'raw/Kx/prompts';out.mkdir()
                    for name in ('kx-0.jsonl','wmp-20.jsonl'):(out/name).write_text('fixture')
                if any(str(a).endswith('/prefix_sched.py') for a in args):
                    name=args[args.index('--run-id')+1];out=Path(args[args.index('--output-dir')+1]);out.mkdir(parents=True)
                    check=name=='Kx-0';n=8 if check else 20
                    groups={g:dict(requests=2 if check else builder.counts(n)[i],failed=0,hit_rate=.5,ttft_p50_s=.1,ttft_p95_s=.2) for i,g in enumerate(prefix_sched.GROUPS)}
                    result=dict(run_id=name,concurrency=int(args[args.index('--concurrency')+1]),ok=n,groups=groups,cache_metric_name='sglang:cache_hit_rate',cache_metric_type='gauge',cache_metric_changed=True,overall_metric_delta=.5,overall_usage_hit_rate=.5,output_tok_per_s=10,request_throughput=1)
                    (out/'summary.json').write_text(json.dumps(result))
                return subprocess.CompletedProcess(args,0)
            with patch.object(kx_006.subprocess,'run',command):kx_006.run(root)
            self.assertEqual(json.loads((scope/'STATE.json').read_text())['steps']['P3b']['status'],'DONE',(scope/'notes/kx_report.md').read_text())
            self.assertEqual([a[-1] for a in calls if '_kx-serve' in a],['fcfs','lpm','fcfs','lpm'])
            clients=[a for a in calls if any(str(v).endswith('/prefix_sched.py') for v in a)]
            self.assertEqual([a[a.index('--concurrency')+1] for a in clients],['1','4','4'])
            self.assertEqual(clients[1][clients[1].index('--prompts')+1],clients[2][clients[2].index('--prompts')+1])
            for a in calls:
                if a[0]=='docker':self.assertEqual(a[a.index('--user')+1],f'{os.getuid()}:{os.getgid()}')
            self.assertEqual(json.loads((scope/'STATE.json').read_text())['steps']['P3b']['status'],'DONE')
            self.assertFalse((root/'STATE.json').exists());self.assertFalse((root/'notes').exists())

    def test_rehearsal_choice_forced_and_production_tie_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scripts=root/'study/scripts';scripts.mkdir(parents=True);atlas=root/'atlas';atlas.mkdir();bin=root/'bin';bin.mkdir()
            for name in ('atlas_export_006.ts','export_support_006.ts','atlas_mac_grade_006.ts'):shutil.copy(ROOT/'scripts'/name,scripts/name)
            git=bin/'git';git.write_text('#!/bin/sh\necho '+finalize_006.PIN+'\n');git.chmod(0o755)
            row=dict(category='no_claim',solved_by_tests=False,grading_pending=True,tool_calls=1,reasoning_observed=True,cache_reporting_verified=True,started_at='2026-10-15T00:00:00Z',ended_at='2026-10-15T00:01:00Z',tokens_out=16)
            for prefix in ('rocm-recipes-006-probe','rocm-recipes-006-rehearsal-probe'):
                for engine in ('vllm','sglang'):
                    for stage in ('smoke','c8'):
                        out=atlas/f'data/{prefix}/live/{engine}-{stage}';out.mkdir(parents=True)
                        tasks=['c13'] if stage=='smoke' else ['c13','c18','c45','c01','c02','c03','c04','c05']
                        (out/'runs.json').write_text(json.dumps(dict(rows=[dict(row,task=t) for t in tasks])))
            env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],REHEARSAL='1')
            choice=root/'study/results/rehearsal/notes/engine_choice.md'
            cmd=['node',str(scripts/'atlas_export_006.ts'),'--choose',str(choice)]
            result=subprocess.run(cmd,cwd=atlas,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            picked=json.loads(choice.with_suffix('.json').read_text())
            self.assertEqual(picked['engine'],'sglang');self.assertTrue(picked['forced']);self.assertTrue(picked['rehearsal']);self.assertIn('force SGLang',choice.read_text())
            result=subprocess.run(cmd,cwd=atlas,env=dict(env,REHEARSAL='0'),capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('Exact tie',result.stderr)

    def test_finalization_cannot_mix_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'live.json';path.write_text(json.dumps(dict(rehearsal=True,atlas_commit=finalize_006.PIN)))
            with self.assertRaisesRegex(ValueError,'mode mismatch'):finalize_006.finalize([path],root)
            self.assertFalse((root/'results/summary.csv').exists())

    def test_summary_cli_rejects_rehearsal_outside_scoped_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=json.loads((ROOT/'inputs/atlas-dry-p08/runs.json').read_text())
            for row in report['rows']:row['rehearsal']=True
            path=root/'report.json';path.write_text(json.dumps(report))
            result=subprocess.run(['python3',str(ROOT/'scripts/summarize_006.py'),str(path),'--allow-fixtures',
                                   '--output-dir',str(root/'bad')],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('results/rehearsal',result.stderr)
            self.assertFalse((root/'bad').exists())

    def test_rehearsal_sync_overrides_stale_production_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir();bin=root/'bin';bin.mkdir();calls=root/'calls'
            shutil.copy(ROOT/'scripts/sync_results.sh',root/'scripts/sync_results.sh')
            (root/'config.env').write_text('DROPLET_IP=old-gpu\nATLAS_SSH_TARGET=root@old-gpu\nATLAS_REMOTE_ROOT=<HOME>/scored\n')
            for name,body in [('rsync','exit 0'),('ssh','echo 0')]:
                p=bin/name;p.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\n'+body+'\n');p.chmod(0o755)
            r=subprocess.run(['bash',str(root/'scripts/sync_results.sh')],env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],CALLS=str(calls),REHEARSAL='1',ATLAS_SSH_TARGET='root@cpu',ATLAS_REMOTE_ROOT='<HOME>/test-rehearsal'),capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('root@cpu:<HOME>/test-rehearsal/results/rehearsal/',calls.read_text())
            self.assertNotIn('old-gpu',calls.read_text());self.assertFalse((root/'logs').exists())


if __name__=='__main__':unittest.main()
