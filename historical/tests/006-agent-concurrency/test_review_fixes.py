"""R1/R2/R3 offline regressions. All setup/grade integrations use explicit fakes."""
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ttft_006
import probe_006
import summarize_006
import gpu_sampler


def prometheus(engine, counts, label='model_name="Qwen/Qwen3.8-27B"'):
    name=ttft_006.METRICS[engine]
    return '\n'.join(f'{name}_bucket{{{label},le="{le}"}} {n}' for le,n in zip(['0.1','0.5','1','+Inf'],counts))


class ProbeTests(unittest.TestCase):
    def test_exact_eight_and_immutable_manifests(self):
        source = ROOT / 'inputs/atlas-b1/c8.json'
        original = json.loads(source.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            atlas=Path(tmp);dest=atlas/'campaigns/rocm-recipes-006/manifests';dest.mkdir(parents=True)
            (dest/'c8.json').write_bytes(source.read_bytes())
            selected=probe_006.prepare(atlas)
            self.assertEqual(selected,['c39','c13','c28','c29','c40','c43','c45','c18'])
            paths=sorted((atlas/'data/rocm-recipes-006-probe').glob('*.json'))
            self.assertEqual(len(paths),4)
            for p in paths:
                d=json.loads(p.read_text())
                self.assertTrue(d['study']['dryRun'])
                self.assertEqual(d['seed'],original['seed'])
                self.assertEqual(d['taskSet'],original['taskSet'])
                self.assertEqual(d['proxyProfiles'],original['proxyProfiles'])
                self.assertEqual(len(d['runs']),1 if 'smoke' in p.name else 8)
                self.assertEqual(d['concurrency'],1 if 'smoke' in p.name else 8)
            before=[p.read_bytes() for p in paths]
            probe_006.prepare(atlas)
            self.assertEqual(before,[p.read_bytes() for p in paths])
            self.assertEqual((dest/'c8.json').read_bytes(),source.read_bytes())


class HistogramTests(unittest.TestCase):
    def records(self, engine='vllm', start=(100,100,100,100), end=(102,108,110,110)):
        return [dict(ts=i,level='c8',boundary=boundary,engine_ttft_histogram=ttft_006.histogram(prometheus(engine,counts),engine))
                for i,boundary,counts in [(0,'before',start),(1,None,start),(2,'after',end)]]

    def test_both_engines_delta_quantiles(self):
        for engine in ('vllm','sglang'):
            r=ttft_006.level_ttft(self.records(engine),'c8')
            self.assertEqual(r['engine_ttft_observations'],10)
            self.assertEqual(r['engine_ttft_status'],'ok')
            self.assertEqual(r['engine_ttft_metric'],ttft_006.METRICS[engine])
            self.assertAlmostEqual(r['engine_ttft_p50_s'],.3)
            self.assertAlmostEqual(r['engine_ttft_p95_s'],.875)
            self.assertIsNone(ttft_006.level_ttft(self.records(engine),'c1')['engine_ttft_p50_s'])

    def test_label_series_aggregate_and_inf(self):
        text=prometheus('vllm',[1,2,3,4],label='worker="1"')+'\n'+prometheus('vllm',[2,3,4,5],label='worker="2"')
        h=ttft_006.histogram(text,'vllm')
        self.assertEqual(len(h['series']),2)
        r=self.records(start=(0,0,0,0),end=(0,0,0,10))
        r[2]['engine_ttft_histogram']=h
        r[0]['engine_ttft_histogram']=ttft_006.histogram(prometheus('vllm',[0,0,0,0],label='worker="1"')+'\n'+prometheus('vllm',[0,0,0,0],label='worker="2"'),'vllm')
        r[1]['engine_ttft_histogram']=r[0]['engine_ttft_histogram']
        result=ttft_006.level_ttft(r,'c8')
        self.assertEqual(result['engine_ttft_observations'],9)
        self.assertEqual(ttft_006.histogram_quantile({'0.1':0,'1.0':0,'+Inf':10},.95),1)

    def test_missing_reset_changes_and_zero_are_null(self):
        for records in [self.records(start=(2,8,10,10),end=(0,0,0,0)),self.records(end=(100,100,100,100))]:
            self.assertIsNone(ttft_006.level_ttft(records,'c8')['engine_ttft_p95_s'])
        r=self.records();r[1]['engine_ttft_histogram']=None
        self.assertIsNone(ttft_006.level_ttft(r,'c8')['engine_ttft_p50_s'])
        r=self.records();r[2]['engine_ttft_histogram']=ttft_006.histogram(prometheus('sglang',[1,2,3,4]),'sglang')
        self.assertEqual(ttft_006.level_ttft(r,'c8')['engine_ttft_status'],'series_changed')
        self.assertIsNone(ttft_006.histogram('sglang:token_usage 0.5','sglang'))
        self.assertIsNone(ttft_006.histogram(prometheus('vllm',[3,1,5,8]),'vllm'))

    def test_existing_sampler_reads_same_metrics_response(self):
        text=prometheus('sglang',[2,4,6,8])+'\nsglang:token_usage 0.4\n'
        with patch.object(gpu_sampler.urllib.request,'urlopen',return_value=io.BytesIO(text.encode())), patch('subprocess.run',side_effect=FileNotFoundError):
            sample=gpu_sampler.sample('sglang')
        self.assertEqual(sample['kv_usage'],.4)
        self.assertEqual(sample['engine_ttft_histogram']['metric'],ttft_006.METRICS['sglang'])

    def test_level_summary_uses_engine_histograms_and_missing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            d=json.loads((ROOT/'inputs/atlas-dry-p08/runs.json').read_text())
            d['rows']=[r for r in d['rows'] if r['level']=='c4']
            for i,r in enumerate(d['rows']):r['missing_status']=i<2
            export=root/'runs.json';export.write_text(json.dumps(d))
            records=self.records();
            start=min(summarize_006.timestamp(r['started_at']) for r in d['rows'])
            end=max(summarize_006.timestamp(r['ended_at']) for r in d['rows'])
            for r,t in zip(records,[start-1,start,end+1]):r['level']='c4';r['ts']=t
            samples=root/'samples.jsonl';samples.write_text('\n'.join(json.dumps(r) for r in records))
            s=summarize_006.summarize([export],[samples],True)[0][0]
            self.assertEqual(s['missing_status_runs'],2)
            self.assertEqual(s['engine_ttft_source'],'engine-side TTFT')
            self.assertAlmostEqual(s['engine_ttft_p50_s'],.3)
            self.assertIsNone(s['ttft_p50_s'])


class BootstrapTests(unittest.TestCase):
    def test_root_bootstrap_with_fakes_records_versions_and_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bin=root/'bin';bin.mkdir();study=root/'study';study.mkdir()
            log=root/'calls';node_dir=root/'node';(node_dir/'bin').mkdir(parents=True)
            def stub(name,body):
                p=bin/name;p.write_text('#!/bin/bash\n'+body+'\n');p.chmod(0o755)
            stub('id',f'''echo "id $*" >> '{log}'
if [[ $1 == -u ]]; then [[ $2 == atlas ]] && echo 1001 || echo 0
elif [[ $1 == atlas && ! -f '{root}/user' ]]; then exit 1
else echo 'uid=1001(atlas) gid=1001(atlas) groups=1001(atlas),999(docker)'; fi''')
            stub('uname','echo x86_64')
            stub('getent',"[[ $1 == passwd ]] && echo 'atlas:x:1001:1001::<HOME>/bin/bash'; exit 0")
            for name in ('apt-get','chown','usermod'):
                stub(name,f"echo '{name}' \"$@\" >> '{log}'")
            stub('useradd',f"echo useradd \"$@\" >> '{log}'; touch '{root}/user'")
            stub('runuser','shift 3; exec "$@"')
            stub('docker',"echo 'Docker 29.1.3 Buildx 0.35.0'")
            stub('tmux',"echo 'tmux 3.4'")
            for name,value in [('node','v24.21.0'),('npm','11.19.0')]:
                p=node_dir/'bin'/name;p.write_text('#!/bin/sh\necho '+value+'\n');p.chmod(0o755)
            (study/'scripts').mkdir()
            helper=(ROOT/'scripts/atlas_ownership_006.sh').read_text().replace('^<HOME>/[A-Za-z0-9_-]+$', '^/[A-Za-z0-9_/-]+$')
            (study/'scripts/atlas_ownership_006.sh').write_text(helper)
            script=root/'bootstrap.sh';script.write_text((ROOT/'scripts/atlas_bootstrap_006.sh').read_text().replace('/opt/atlas-node-$NODE_VERSION',str(node_dir)))
            r=subprocess.run(['bash',str(script),str(study)],env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH']),capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            versions=json.loads((study/'logs/bootstrap_versions.json').read_text())
            self.assertEqual(versions['node'],'v24.21.0');self.assertEqual(versions['tmux'],'tmux 3.4')
            self.assertIn('useradd',log.read_text());self.assertIn('usermod -aG docker atlas',log.read_text())
            self.assertIn('apt-get install',log.read_text())


class MacHandoffTests(unittest.TestCase):
    def test_pending_audited_and_changed_evidence_without_models(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();study=root/'study'
            run_id='c13__qwen38-27b-mi300x__a1'
            pending=study/'results/grading/pending'/run_id;pending.mkdir(parents=True)
            native=pending/'native-tests';native.mkdir();(native/'tests.json').write_text('{}')
            trace=root/'trace.json';trace.write_text('{}')
            sha=lambda b:hashlib.sha256(b).hexdigest()
            row=dict(run_id=run_id,state='finished',trace_path=str(trace),task_id='c13',end_reason='completed')
            modules={
                'runner/store.ts':f"export class Store {{db={{prepare:()=>({{get:()=>({{manifest_json:'{{}}'}})}})}}; acquire(){{return 'fake';}} release(){{}} close(){{}} row(){{return {json.dumps(row)};}}}}",
                'grading/evidence.ts':"import {readFile} from 'node:fs/promises';export const artifactText=async p=>readFile(p,'utf8');export function readEvidence(){throw Error('unexpected evidence recomputation');}",
                'grading/grader.ts':"export function gradeTests(){throw Error('No Docker/native checks allowed in cached handoff test');}",
                'grading/task.ts':"export function gradingTask(){throw Error('unexpected native grading');}",
                'grading/tree.ts':"export const treeHash=async()=> 'workspace-hash';",
                'grading/tamper.ts':"export const captureProtection=()=>{},compareProtection=()=>{};",
                'runner/host/images.ts':"export const recheckRuntime=()=>{};",
                'grading/cost.ts':"export const readPrices=()=>{},computeCost=()=>{};",
                'grading/taxonomy.ts':"export const observedAgentWork=()=>{},secondaryFlags=()=>{};export const categorize=x=>x.infra?'infra_error':x.testsPassed?'solved':'false_success';",
                'grading/cutoff.ts':"export const taskProvenance=()=>{};",
                'grading/redact.ts':"export const redact=x=>x;",
            }
            for path,text in modules.items():
                p=atlas/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            request=dict(version=1,run_id=run_id,level='c1',trace_sha256=sha(b'{}'),workspace_sha256='workspace-hash',native_tests_sha256=sha(b'{}'),work=True,
                record=dict(tests=dict(testsPassed=True),protection=dict(tamper=False),executionRow=row))
            request_path=pending/'request.json';request_path.write_text(json.dumps(request))
            bin=root/'bin';bin.mkdir();git=bin/'git';git.write_text('#!/bin/sh\necho '+summarize_006.PIN+'\n');git.chmod(0o755)
            script=root/'check.mjs';script.write_text("import {missingGrade} from "+json.dumps(str(ROOT/'scripts/atlas_mac_grade_006.ts'))+";console.log(JSON.stringify(await missingGrade("+json.dumps(run_id)+",'c1','fake.db',"+json.dumps(str(study))+")));\n")
            def invoke():return subprocess.run(['node',str(script)],cwd=atlas,env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH']),capture_output=True,text=True)
            r=invoke();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'null')
            returned=study/'results/grading/returned'/run_id;returned.mkdir(parents=True)
            response=dict(atlas_commit=summarize_006.PIN,run_id=run_id,request_sha256=sha(request_path.read_bytes()),category='solved',claim=dict(source='llm_fallback',claim='done',audited=False))
            (returned/'response.json').write_text(json.dumps(response))
            self.assertNotEqual(invoke().returncode,0)
            response['claim']['audited']=True
            (returned/'response.json').write_text(json.dumps(response))
            (returned/'audit.json').write_text(json.dumps(dict(accepted=True,expected='done',reported='done',reviewer='test reviewer',reason='offline fixture')))
            r=invoke();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['category'],'solved')
            trace.write_text('{"changed":true}')
            r=invoke();self.assertNotEqual(r.returncode,0);self.assertIn('inputs changed',r.stderr)

    def test_new_pin_and_native_map_commands_present(self):
        text=(ROOT/'scripts/atlas_remote.sh').read_text()
        self.assertIn(summarize_006.PIN,text)
        self.assertIn('prepare-host data/rocm-recipes-006-native',text)
        self.assertIn('check-host "$IMAGE_MAP"',text)
        self.assertIn('--image-map "$IMAGE_MAP"',text)
        self.assertNotIn("t.image)throw Error('Missing dependency image",text)

class FreshMacHandoffTests(unittest.TestCase):
    def test_fresh_native_handoff_and_fake_mac_audit(self):
        # The fake package exports only pinned API shapes. No Docker/model process is available.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();study=root/'study'
            trace=root/'trace.json';stdout=root/'stdout';stdout.write_text('work observed')
            diff=root/'diff';diff.write_text('changed implementation')
            (root/'protection-before.json').write_text('{}')
            trace.write_text(json.dumps(dict(result=dict(stdoutPath=str(stdout)))))
            row=dict(run_id='fixture',state='finished',trace_path=str(trace),task_id='c13',end_reason='completed',backend='local',harness='opencode',model='Qwen/Qwen3.8-27B',wall_s=1,diff_path=str(diff),config_json='{}')
            modules={
                'runner/store.ts':f"export class Store {{db={{prepare:()=>({{get:()=>({{manifest_json:'{{\"study\":{{\"dryRun\":false}}}}'}})}})}};acquire(){{return 'fake';}}release(){{}}close(){{}}row(){{return {json.dumps(row)};}}}}",
                'grading/evidence.ts':"import{readFile}from'node:fs/promises';export const artifactText=async p=>readFile(p,'utf8');export const readEvidence=async()=>({finalMessage:'Finished without a status line',tokens:{input:1,output:1,cached:0},raw:[],toolCalls:[],tokenSource:'proxy',noRequests:false});",
                'grading/grader.ts':"import{mkdir,writeFile}from'node:fs/promises';import{join}from'node:path';export async function gradeTests(w,t,d){await mkdir(d,{recursive:true});const r={directory:d,status:'passed',testsPassed:true};await writeFile(join(d,'tests.json'),JSON.stringify(r));return r;}",
                'grading/task.ts':"export const gradingTask=async()=>({image:'fake'});",
                'grading/tree.ts':"export const treeHash=async()=> 'workspace-hash';",
                'grading/tamper.ts':"export const captureProtection=async()=>({}),compareProtection=()=>({tamper:false});",
                'runner/host/images.ts':"export const recheckRuntime=()=>{};",
                'grading/cost.ts':"export const readPrices=async()=>({}),computeCost=()=>({costUsd:0});",
                'grading/taxonomy.ts':"export const observedAgentWork=()=>true,secondaryFlags=()=>[];export const categorize=x=>x.infra?'infra_error':x.testsPassed?'solved':'false_success';",
                'grading/cutoff.ts':"export const taskProvenance=async()=>({});",
                'grading/redact.ts':"export const redact=x=>x;",
                'local/server.ts':"export const startMlx=async()=>({stop:async()=>{}});",
                'grading/claim.ts':"import{mkdir,writeFile}from'node:fs/promises';import{join}from'node:path';export async function classifyClaim(m,d){const p=join(d,'fixture');await mkdir(p,{recursive:true});return{claim:'done',source:'llm_fallback',audited:false,callDirectory:p};}export async function auditClaim(r,c,reviewer,reason){if(c!==r.claim)throw Error('audit disagrees');await writeFile(join(r.callDirectory,'audit.json'),JSON.stringify({accepted:true,expected:c,reported:r.claim,reviewer,reason}));return{...r,audited:true};}",
            }
            for path,text in modules.items():
                p=atlas/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            bin=root/'bin';bin.mkdir();git=bin/'git';git.write_text('#!/bin/sh\necho '+summarize_006.PIN+'\n');git.chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'])
            helper=ROOT/'scripts/atlas_mac_grade_006.ts'
            script=root/'run.mjs';script.write_text('import{missingGrade}from '+json.dumps(str(helper))+';console.log(JSON.stringify(await missingGrade("fixture","c1","fake.db",'+json.dumps(str(study))+')));')
            def run(*args):return subprocess.run(['node',*map(str,args)],cwd=atlas,env=env,capture_output=True,text=True)
            r=run(script);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'null')
            request=study/'results/grading/pending/fixture/request.json'
            self.assertTrue(request.exists())
            original=request.read_bytes()
            isolated=root/'isolated.mjs'
            isolated.write_text('import{missingGrade}from '+json.dumps(str(helper))+';console.log(JSON.stringify(await missingGrade("fixture","c1","fake.db",'+json.dumps(str(study))+',true,'+json.dumps(str(study/'results'))+',"sglang-smoke__fixture")));')
            r=run(isolated);self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue(json.loads(r.stdout)['grading_pending'])
            self.assertTrue((study/'results/grading/pending/sglang-smoke__fixture/request.json').exists())
            self.assertEqual(request.read_bytes(),original)
            # Current Mac can exercise the CLI with a fake MLX module; Linux must refuse it.
            out=study/'results/grading/returned/fixture';out.parent.mkdir(parents=True)
            r=run(helper,'classify',request,out)
            if sys.platform!='darwin':
                self.assertNotEqual(r.returncode,0);self.assertIn('Mac-only',r.stderr);return
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertFalse((out/'response.json').exists())
            again=run(helper,'classify',request,out);self.assertNotEqual(again.returncode,0)
            r=run(helper,'audit',request,out,'done','test reviewer','offline fake model')
            self.assertEqual(r.returncode,0,r.stderr)
            r=run(script);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['category'],'solved')

if __name__=='__main__':unittest.main()
