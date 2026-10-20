"""Real c16 retry-2 shape and the cached retry-1 grade that blocked its export."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
import sys
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ATLAS=Path(os.environ.get('ATLAS_SOURCE','<WORKDIR>/lab/atlas'))
sys.path.insert(0,str(ROOT/'scripts'))
import finalize_006 as finalizer
import summarize_006 as summary
import session4_setup_006 as setup
import session4_flow_006 as flow
import session4_recover_006 as recover


class Retry2ExportTests(unittest.TestCase):
    def test_restore_preserves_evidence_and_rejects_symlink_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=root/'results/session4';scope.mkdir(parents=True);atlas=root/'atlas';atlas.mkdir()
            archive=scope/'resume_data.tar.gz'
            with tarfile.open(archive,'w:gz') as t:
                d=tarfile.TarInfo('data');d.type=tarfile.DIRTYPE;d.mode=0o700;t.addfile(d)
                f=tarfile.TarInfo('data/retained.json');f.size=2;f.mode=0o600;t.addfile(f,io.BytesIO(b'{}'))
            manifest=scope/'resume.json';manifest.write_text(json.dumps(dict(files={archive.name:recover.sha(archive)})))
            recover.restore(root,atlas);self.assertEqual((atlas/'data/retained.json').read_text(),'{}')
            with self.assertRaisesRegex(ValueError,'fresh ATLAS'):recover.restore(root,atlas)
            other=root/'other';other.mkdir()
            with tarfile.open(archive,'w:gz') as t:
                link=tarfile.TarInfo('data/escape');link.type=tarfile.SYMTYPE;link.linkname='/tmp';t.addfile(link)
                f=tarfile.TarInfo('data/escape/forbidden');f.size=0;t.addfile(f,io.BytesIO(b''))
            manifest.write_text(json.dumps(dict(files={archive.name:recover.sha(archive)})))
            with self.assertRaisesRegex(ValueError,'traverses symlink'):recover.restore(root,other)
            self.assertFalse((other/'data').exists())
            manifest.write_text(json.dumps(dict(files={archive.name:'wrong'})))
            with self.assertRaisesRegex(ValueError,'checkpoint changed'):recover.restore(root,other)

    def test_completed_c16_resumes_c8_then_c4_c1_with_unchanged_guard(self):
        now=datetime.now(timezone.utc)
        env=dict(REHEARSAL='0',CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='10')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,env),patch.object(flow,'verify_bundle'),patch.object(flow,'budget',side_effect=lambda root,plan,level,seconds,remaining:dict(remaining=list(remaining),dropped=[])) as guard:
            root=Path(tmp)
            for path,value in [('atlas/data/rocm-recipes-006-session4/session4.json',{}),('inputs/session4/engine_choice.json',{'engine':'vllm'}),('results/session4/pending_native.json',{'runs':[{'status':'complete'}]}),('results/session4/progress.json',dict(completed=[dict(level='c16')],remaining=['c8','c4','c1'],active=None))]:
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
            (root/'logs').mkdir();(root/'logs/current_server.json').write_text((ROOT/'results/droplet_logs/current_server.json').read_text())
            (root/'STATE.json').write_text((ROOT/'STATE.json').read_text())
            order=[];flow.run(root,dispatch=order.append)
            self.assertEqual(order,['c8','c4','c1'])
            self.assertEqual([call.args[2] for call in guard.call_args_list],order)

    def test_new_host_grade_records_provenance_and_rejects_arm64(self):
        fixture=json.loads(gzip.decompress((ROOT/'inputs/reh005-retry2.json.gz').read_bytes()))
        row=fixture['retry2_row'];entry=fixture['grade']['execution']['hostImage']['entry']
        oldhost=fixture['grade']['execution']['hostImage']['host']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();bin=root/'bin';bin.mkdir()
            git=bin/'git';git.write_text('#!/bin/sh\necho 279889b8f42c607344781766503602a8c462f5df\n');git.chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'])
            oldmap=dict(tasks={'c09':entry},host=oldhost,frozen={'tagCommit':'tasks-v1'},runtimeSha256='runtime')
            raw=json.dumps(oldmap).encode();image_map=root/'results/session4/execution-image-map.json';image_map.parent.mkdir(parents=True);image_map.write_bytes(raw)
            trace=atlas/'data'/row['trace_path'].split('/atlas/data/')[1];trace.parent.mkdir(parents=True)
            workspace=trace.parent/'workspace';workspace.mkdir();(workspace/'file').write_text('retained task')
            (trace.parent/'protection-before.json').write_text('{}')
            proxy=atlas/'data/proxy.jsonl';proxy.write_text(json.dumps(dict(event='response',request_id='one',token_source='proxy',tokens_in=1,tokens_out=1,tokens_cached=0,tokens_cache_write=0,inference_s=1,response={}))+'\n')
            execution=dict(proxy_log='<HOME>/rocm-recipes-006/atlas/data/proxy.jsonl',hostImage=dict(host=oldhost,entry=entry,mapSha256=hashlib.sha256(raw).hexdigest()))
            trace.write_text(json.dumps(execution))
            newmap=dict(oldmap,host=dict(daemonId='new-amd64-daemon',platform='linux/amd64'),tasks={'c09':dict(entry,image='sha256:'+'a'*64)})
            modules={
                'grading/evidence.ts':'export {artifactText,readEvidence} from '+json.dumps(str(ATLAS/'grading/evidence.ts'))+';',
                'runner/store.ts':'export class Store{row(){return '+json.dumps(row)+';}close(){}}',
                'grading/grader.ts':'import{writeFile}from"node:fs/promises";export async function gradeTests(workspace,task,out){if(task.image!=="sha256:'+'a'*64+'")throw Error("old image used");await writeFile("graded-marker","yes");return {testsPassed:true,status:"passed"};}',
                'grading/task.ts':'export async function gradingTask(){return {image:"old-image",preparation:[]};}',
                'grading/tamper.ts':'export async function captureProtection(){return {};}export function compareProtection(){return {tamper:false};}',
                'grading/taxonomy.ts':'export{categorize}from '+json.dumps(str(ATLAS/'grading/taxonomy.ts'))+';',
                'grading/claim.ts':'export function parseStatus(){return null;}',
            }
            def image_module():
                p=atlas/'runner/host/images.ts';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('export async function loadHostMap(){return '+json.dumps(dict(map=newmap,sha256='new-map-sha'))+';}')
            for name,body in modules.items():
                p=atlas/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
            image_module()
            helper=ROOT/'scripts/session4_retained_006.ts'
            extract=subprocess.run(['node',str(helper),'extract',str(atlas/'data'),str(atlas)],cwd=atlas,env=env,input=json.dumps(row),capture_output=True,text=True)
            self.assertEqual(extract.returncode,0,extract.stderr)
            pending=dict(runs=[dict(row=row,proof=json.loads(extract.stdout)['proof'],status='pending')])
            path=root/'results/session4/pending_native.json';path.write_text(json.dumps(pending))
            report=atlas/'data/rocm-recipes-006/live/c16/runs.json';report.parent.mkdir(parents=True)
            report.write_text(json.dumps(dict(rows=[dict(run_id=row['run_id'],native_grade_pending=True)],pending_mac_grades=0)))
            command=['node',str(helper),'grade',str(root),str(atlas)]
            result=subprocess.run(command,cwd=atlas,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            graded=json.loads(report.read_text())['rows'][0]
            self.assertEqual(graded['grading_host']['daemonId'],'new-amd64-daemon')
            self.assertTrue(graded['grading_host_changed']);self.assertFalse(graded['native_grade_pending'])
            self.assertEqual(graded['execution_host'],oldhost)
            self.assertEqual(graded['category'],'turn_cap')
            # A retry is idempotent; a wrong host cannot perform pending grading.
            result=subprocess.run(command,cwd=atlas,env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
            newmap['host']['platform']='linux/arm64';image_module();(atlas/'graded-marker').unlink()
            path.write_text(json.dumps(pending));result=subprocess.run(command,cwd=atlas,env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('checked amd64',result.stderr)
            self.assertFalse((atlas/'graded-marker').exists())

    def test_pending_native_never_scores_or_finalizes(self):
        source=ROOT/'results/atlas/scored/live/c16/runs.json'
        original=json.loads(source.read_text())
        # Real last-live shape, plus the real missing execution identity.
        fixture=json.loads(gzip.decompress((ROOT/'inputs/reh005-retry2.json.gz').read_bytes()))
        row=fixture['retry2_row'];pending=dict(original['rows'][-1],run_id=row['run_id'],native_grade_pending=True,excluded=True,solved_by_tests=None,category='native_grade_pending')
        report=dict(original,rows=original['rows'][:31]+[pending],pending_native_grades=1,execution_complete=True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'runs.json';path.write_text(json.dumps(report))
            levels,rows=summary.summarize([path],allow_pending=True)
            self.assertEqual(levels[0]['pending_native_grades'],1)
            self.assertFalse(next(r for r in rows if r['run_id']==row['run_id'])['included'])
            without=Path(tmp)/'before.json';without.write_text(json.dumps(dict(original,rows=original['rows'][:31])))
            previous,_=summary.summarize([without],allow_pending=True)
            for field in ['runs','solved','failure_other','failure_timeout','failure_infra','failure_turn_cap']:
                self.assertEqual(levels[0][field],previous[0][field],field)
            with self.assertRaisesRegex(ValueError,'pending native'):finalizer.finalize([path],Path(tmp))
            queue=Path(tmp)/'results/session4/pending_native.json';queue.parent.mkdir(parents=True);queue.write_text('{"runs":[{"status":"pending"}]}')
            with self.assertRaisesRegex(ValueError,'pending native'):finalizer.finalize([],Path(tmp))

    def test_pending_stage_after_check_host_and_before_proxy(self):
        calls=[]
        def command(args,**kw):calls.append(args);return subprocess.CompletedProcess(args,0)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,VLLM_IMAGE='vllm',SCRATCH_DIR=tmp),patch.object(setup.subprocess,'run',side_effect=command),patch.object(setup,'run_cancellable',side_effect=lambda args,cancel,**kw:command(args,**kw)):
            root=Path(tmp);p=root/'results/session4/pending_native.json';p.parent.mkdir(parents=True);p.write_text('{"runs":[]}')
            setup.setup(root,root)
            check=next(i for i,c in enumerate(calls) if 'check-host' in c)
            grade=next(i for i,c in enumerate(calls) if c[0]=='node' and 'session4_retained_006.ts' in c[1])
            proxy=next(i for i,c in enumerate(calls) if 'proxy/build.ts' in c)
            self.assertLess(check,grade);self.assertLess(grade,proxy)

    def test_flow_blocks_c8_until_pending_native_completed(self):
        now=datetime.now(timezone.utc)
        env=dict(REHEARSAL='0',CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='10')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,env),patch.object(flow,'verify_bundle'):
            root=Path(tmp)
            for path,value in [('atlas/data/rocm-recipes-006-session4/session4.json',{}),('inputs/session4/engine_choice.json',{'engine':'vllm'}),('results/session4/pending_native.json',{'runs':[{'status':'pending'}]})]:
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
            (root/'logs').mkdir();(root/'logs/current_server.json').write_text((ROOT/'results/droplet_logs/current_server.json').read_text())
            with self.assertRaisesRegex(ValueError,'before c8'):flow.run(root,dispatch=lambda _:self.fail('dispatched before grading'))

    def test_real_retry2_revisits_bounded_lossless_retry1_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'fixture.json'
            fixture.write_bytes(gzip.decompress((ROOT/'inputs/reh005-retry2.json.gz').read_bytes()))
            script=root/'check.mts'
            script.write_text('''
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir,lstat,symlink} from 'node:fs/promises';
import {join} from 'node:path';
import {compactGrade} from '''+json.dumps(str(ROOT/'scripts/export_support_006.ts'))+''';
import {artifactText} from '''+json.dumps(str(ATLAS/'grading/evidence.ts'))+''';
import {redact} from '''+json.dumps(str(ATLAS/'grading/redact.ts'))+''';
const fixture=JSON.parse(await readFile('fixture.json','utf8'));
const grade=fixture.grade,row=fixture.retry2_row;
assert.deepEqual(redact(grade),grade);
assert.equal(row.attempt,1162);
assert.equal(row.retry_of,grade.runId);
assert.equal(row.end_reason,'turn_cap');
assert.equal(grade.executionRow.attempt,1161);
assert.equal(grade.fingerprint,fixture.retry1_grade_metadata.fingerprint);
const directory=join(process.cwd(),'data/grading/retry1'),path=join(directory,'grade.json');
await mkdir(directory,{recursive:true});
const original=JSON.stringify(grade,null,2);
await writeFile(path,original);
assert.equal(Buffer.byteLength(original),36817225);
await assert.rejects(artifactText(path),/bounded regular file/);
const compacted=await compactGrade(grade,'''+json.dumps(str(ATLAS))+''',directory);
assert.ok(compacted.compact_bytes<=32*1024*1024);
assert.deepEqual(JSON.parse(await artifactText(path)),redact(grade));
assert.equal(await readFile(path+'.pretty-original','utf8'),original);
// Retry-2's export revisits the retry-1 cache through the unchanged reader.
assert.equal(JSON.parse(await artifactText(path)).runId,row.retry_of);
assert.equal(await compactGrade(grade,'''+json.dumps(str(ATLAS))+''',directory),null);
// An actually oversized compact record still fails, with its source preserved.
const big=join(process.cwd(),'data/grading/too-big');await mkdir(big,{recursive:true});
const excessive={directory:big,status:'complete',payload:'x'.repeat(32*1024*1024)};
await writeFile(join(big,'grade.json'),JSON.stringify(excessive,null,2));
await assert.rejects(compactGrade(excessive,'''+json.dumps(str(ATLAS))+'''),/still exceeds strict artifact bound/);
await assert.rejects(artifactText(join(big,'grade.json')),/bounded regular file/);
// A path outside data and a symlink escape remain forbidden by the real guard.
await writeFile('outside.json','{}');
await assert.rejects(artifactText('outside.json'),/bounded regular file/);
await symlink(join(process.cwd(),'outside.json'),'data/escape.json');
await assert.rejects(artifactText('data/escape.json'),/bounded regular file/);
await mkdir('data/not-a-file');
await assert.rejects(artifactText('data/not-a-file'),/bounded regular file/);
console.log(JSON.stringify({retry2:row.run_id,...compacted,strict_guard_unchanged:true}));
''')
            result=subprocess.run(['node',str(script)],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('strict_guard_unchanged',result.stdout)


if __name__=='__main__':unittest.main()
