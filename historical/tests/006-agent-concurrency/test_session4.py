"""Amendment A: interrupted export, immutable resume, budget boundaries and setup."""
import copy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ATLAS=Path(os.environ.get('ATLAS_SOURCE','<WORKDIR>/lab/atlas'))
sys.path.insert(0,str(ROOT/'scripts'))
import session4_006 as s4
import session4_setup_006 as setup
import session4_flow_006 as flow
import session4_retry_006 as retries
import summarize_006 as summary


class ResumeTests(unittest.TestCase):
    def test_frozen_manifests_resume_same_db_and_native_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir()
            (atlas/'campaigns').symlink_to(ATLAS/'campaigns',target_is_directory=True)
            (root/'inputs').mkdir();shutil.copytree(ROOT/s4.BUNDLE,root/s4.BUNDLE)
            plan=s4.prepare(root,atlas)
            self.assertEqual(plan['order'],['c16','c8','c4','c1'])
            first=[r['task'] for r in s4.frozen(ATLAS,'c1')['runs'][:10]]
            self.assertEqual(plan['matched_tasks'],first)
            self.assertEqual([plan['levels'][l]['new_runs'] for l in plan['order']],[30,30,30,7])
            c1=json.loads((atlas/s4.CAMPAIGN/'c1.json').read_text())
            self.assertEqual([r['task'] for r in c1['runs']],[t for t in first if t not in {'c18','c09','c28'}])
            self.assertEqual(c1['runs'][0]['retryOf'],'c22__qwen38-27b-mi300x__a1')
            for level in plan['order']:
                m=json.loads((atlas/s4.CAMPAIGN/(level+'.json')).read_text());original=s4.frozen(ATLAS,level)
                for key in ('taskSet','proxyProfiles','perRunS','seed','mode','localCost'):
                    self.assertEqual(m[key],original[key])
                self.assertEqual(m['study']['repetitions'],1)
                self.assertEqual(len(m['runs']),len({r['task'] for r in m['runs']}))
            dbpath=atlas/'data/rocm-recipes-006/atlas.db'
            before=s4.sha(dbpath)
            # Real pinned loader + Store: derived IDs coexist with original immutable membership.
            code=f"""import{{loadManifest}}from{json.dumps(str(ATLAS/'runner/manifest.ts'))};
import{{Store}}from{json.dumps(str(ATLAS/'runner/store.ts'))};
const store=new Store({json.dumps(str(dbpath))});
try{{for(const l of ['c16','c8','c4','c1'])store.register(await loadManifest({json.dumps(str(atlas/s4.CAMPAIGN))}+'/'+l+'.json'));}}
finally{{store.close();}}
"""
            p=root/'register.mts';p.write_text(code)
            r=subprocess.run(['node',str(p)],cwd=ATLAS,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            db=sqlite3.connect(dbpath);db.row_factory=sqlite3.Row
            history=json.loads(gzip.decompress((root/s4.BUNDLE/'history.json.gz').read_bytes()))
            for entry in history['entries']:
                self.assertEqual(dict(db.execute('SELECT * FROM runs WHERE run_id=?',(entry['row']['run_id'],)).fetchone()),entry['row'])
            db.close();self.assertNotEqual(before,s4.sha(dbpath));s4.verify_bundle(ROOT/s4.BUNDLE)

    def test_resume_bundle_rejects_changed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bundle';shutil.copytree(ROOT/s4.BUNDLE,path)
            (path/'engine_choice.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):s4.verify_bundle(path)

    def test_infra_retry_is_new_id_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();(atlas/'campaigns').symlink_to(ATLAS/'campaigns',target_is_directory=True)
            (root/'inputs').mkdir();shutil.copytree(ROOT/s4.BUNDLE,root/s4.BUNDLE)
            s4.prepare(root,atlas);campaign=atlas/s4.CAMPAIGN;dbpath=atlas/'data/rocm-recipes-006/atlas.db'
            # Insert the new c22 infra attempt while other six are terminal timeouts.
            db=sqlite3.connect(dbpath)
            for spec in json.loads((campaign/'c1.json').read_text())['runs']:
                source=db.execute('SELECT * FROM runs WHERE task_id=?',(spec['task'],)).fetchone()
                cols=[v[1] for v in db.execute('PRAGMA table_info(runs)')];row=dict(zip(cols,source))
                row.update(run_id=f"{spec['task']}__{spec['config']}__a6",state='finished',attempt=6,retry_of=spec.get('retryOf'),end_reason='infra' if spec['task']=='c22' else 'timeout',category=None)
                db.execute('INSERT INTO runs VALUES('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
            db.commit();db.close()
            path=retries.retry(campaign,dbpath,'c1',1);m=json.loads(path.read_text())
            self.assertEqual(len(m['runs']),1);self.assertEqual(m['runs'][0]['retryOf'],'c22__qwen38-27b-mi300x__a6')
            db=sqlite3.connect(dbpath);cols=[v[1] for v in db.execute('PRAGMA table_info(runs)')]
            row=dict(zip(cols,db.execute("SELECT * FROM runs WHERE run_id='c22__qwen38-27b-mi300x__a6'").fetchone()))
            row.update(run_id=f"c22__qwen38-27b-mi300x__a{m['runs'][0]['attempt']}",retry_of='c22__qwen38-27b-mi300x__a6')
            db.execute('INSERT INTO runs VALUES('+','.join('?' for _ in cols)+')',[row[k] for k in cols]);db.commit();db.close()
            self.assertIsNone(retries.retry(campaign,dbpath,'c1',2))


class InterruptedExporterTests(unittest.TestCase):
    def test_actual_exporter_session3_c22_null_paths_never_call_grader(self):
        actual=json.loads((ROOT/'inputs/session3-c22-row.json').read_text())
        for variant in ('null-trace','null-nested-evidence','infra-with-trace'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);study=root/'study';scripts=study/'scripts';scripts.mkdir(parents=True);atlas=root/'atlas';atlas.mkdir();bin=root/'bin';bin.mkdir()
                for name in ('atlas_export_006.ts','atlas_mac_grade_006.ts','export_support_006.ts','summarize_006.py','ttft_006.py'):
                    shutil.copyfile(ROOT/'scripts'/name,scripts/name)
                row=copy.deepcopy(actual);trace=root/'execution.json';trace.write_text(json.dumps(dict(result=dict(stdoutPath=None),proxy_log=None)))
                row['trace_path']=None if variant=='null-trace' else str(trace)
                manifest=dict(id='session3-interrupted',study=dict(level='c1',dryRun=False))
                modules={
                    'runner/manifest.ts':f'export const loadManifest=async()=>({{manifest:{json.dumps(manifest)},runs:[{{runId:{json.dumps(row["run_id"])}}}]}});',
                    'runner/store.ts':f'export class Store{{db={{prepare:()=>({{get:()=>undefined}})}};row(){{return {json.dumps(row)};}}close(){{}}}}',
                    'grading/service.ts':'export const gradeRun=()=>{throw Error("must not grade interrupted execution");};',
                    'grading/claim.ts':'export const parseStatus=()=>null;',
                    'grading/evidence.ts':'export const artifactText=()=>{throw Error("must not read infra evidence path");};export const readEvidence=()=>{throw Error("must not read infra evidence");};',
                }
                for path,body in modules.items():
                    p=atlas/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
                git=bin/'git';git.write_text('#!/bin/sh\necho '+s4.PIN+'\n');git.chmod(0o755)
                db=atlas/'data/campaign/atlas.db'
                result=subprocess.run(['node',str(scripts/'atlas_export_006.ts'),'manifest',str(db)],cwd=atlas,env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],REHEARSAL='0'),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                report=json.loads((db.parent/'live/c1/runs.json').read_text());r=report['rows'][0]
                self.assertEqual(r['category'],'infra_error');self.assertIsNone(r['evidence_path']);self.assertIsNone(r['tokens_in']);self.assertIsNone(r['tests_passed']);self.assertFalse(r['solved_by_tests'])
                with (study/'results/live/summary.csv').open() as f:
                    import csv
                    level=next(csv.DictReader(f));self.assertEqual(level['infra_attempts'],'1');self.assertEqual(level['runs'],'0')

    def test_actual_exporter_reuses_bound_session3_native_grades_without_old_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);study=root/'study';scripts=study/'scripts';scripts.mkdir(parents=True)
            atlas=root/'atlas';atlas.mkdir();bin=root/'bin';bin.mkdir();(study/'inputs').mkdir()
            shutil.copytree(ROOT/s4.BUNDLE,study/s4.BUNDLE)
            for name in ('atlas_export_006.ts','atlas_mac_grade_006.ts','export_support_006.ts','session4_006.py','summarize_006.py','ttft_006.py'):
                shutil.copyfile(ROOT/'scripts'/name,scripts/name)
            campaign=atlas/s4.CAMPAIGN;campaign.mkdir(parents=True)
            manifest=dict(id='rocm006-session4-c1',study=dict(level='c1',dryRun=False))
            history=json.loads(gzip.decompress((study/s4.BUNDLE/'history.json.gz').read_bytes()))
            (campaign/'session4.json').write_text(json.dumps(dict(history=str(study/s4.BUNDLE/'history.json.gz'),matched_tasks=history['matched_tasks'])))
            db=atlas/'data/rocm-recipes-006/atlas.db';db.parent.mkdir(parents=True);shutil.copyfile(study/s4.BUNDLE/'atlas.db',db)
            modules={
                'runner/manifest.ts':f'export const loadManifest=async()=>({{manifest:{json.dumps(manifest)},runs:[]}});',
                'runner/store.ts':'export {Store} from '+json.dumps(str(ATLAS/'runner/store.ts'))+';',
                'grading/service.ts':'export const gradeRun=()=>{throw Error("must retain historical native verdicts");};',
                'grading/claim.ts':'export const parseStatus=()=>null;',
                'grading/evidence.ts':'export const readEvidence=()=>{throw Error("old-host evidence must stay immutable");};export const artifactText=()=>{throw Error("no old-host reads");};',
            }
            for path,body in modules.items():
                p=atlas/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
            git=bin/'git';git.write_text('#!/bin/sh\necho '+s4.PIN+'\n');git.chmod(0o755)
            r=subprocess.run(['node',str(scripts/'atlas_export_006.ts'),str(campaign/'c1.json'),str(db)],cwd=atlas,env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],REHEARSAL='0'),capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            report=json.loads((db.parent/'live/c1/runs.json').read_text());self.assertEqual(len(report['rows']),4)
            for row in report['rows']:
                original=next(e for e in history['entries'] if e['row']['run_id']==row['run_id'])
                self.assertEqual(row['study_session'],3)
                if original['grade']:
                    self.assertEqual(row['tests_passed'],original['grade']['tests']['testsPassed'])
                    self.assertEqual(row['tamper'],original['grade']['protection']['tamper'])
                    self.assertEqual(row['category'],original['grade']['category'])
                else:self.assertEqual(row['category'],'infra_error')


class BudgetTests(unittest.TestCase):
    def test_drop_c1_then_c4_and_never_drop_c8(self):
        counts=dict(c16=30,c8=30,c4=30,c1=7)
        for elapsed,expected,dropped,wrap in [(2,['c8','c4'],['c1'],False),(5,['c8'],['c1','c4'],False),(8,[],['c1','c4'],True)]:
            d=s4.projection(elapsed,3600,30,16,['c8','c4','c1'],counts)
            self.assertEqual(d['remaining'],expected);self.assertEqual(d['dropped'],dropped);self.assertEqual(d['wrap'],wrap)
        d=s4.projection(7.5,3600,30,16,['c8'],counts)
        self.assertEqual(d['projected_hours'],10.5);self.assertFalse(d['wrap'])

    def test_invalid_cap_or_deadline_fails_before_dispatch(self):
        now=datetime.now(timezone.utc)
        env=dict(CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='9')
        with patch.dict(os.environ,env),self.assertRaisesRegex(ValueError,'cap=10'):s4.lifecycle(now)
        env['SESSION_CAP_HOURS']='10'
        with patch.dict(os.environ,env):self.assertEqual(s4.lifecycle(now),0)

    def test_flow_checks_budget_only_after_each_completed_dispatch(self):
        now=datetime.now(timezone.utc)
        env=dict(REHEARSAL='0',CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='10')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,env):
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();(atlas/'campaigns').symlink_to(ATLAS/'campaigns',target_is_directory=True)
            (root/'inputs').mkdir();shutil.copytree(ROOT/s4.BUNDLE,root/s4.BUNDLE)
            s4.prepare(root,atlas);shutil.copyfile(ROOT/'STATE.json',root/'STATE.json')
            (root/'logs').mkdir();(root/'logs/current_server.json').write_text((ROOT/'results/droplet_logs/current_server.json').read_text())
            events=[]
            def dispatch(level):events.append('finished '+level)
            def guard(root,plan,level,seconds,remaining):
                events.append('guard '+level)
                self.assertEqual(events[-2],'finished '+level)
                return dict(remaining=['c8'] if level=='c16' else [],dropped=['c1','c4'])
            with patch.object(flow,'budget',side_effect=guard):flow.run(root,dispatch=dispatch)
            self.assertEqual(events,['finished c16','guard c16','finished c8','guard c8'])
            # A reconnect must not redispatch completed levels from the beginning.
            with patch.object(flow,'budget',side_effect=AssertionError('no extra guard')):flow.run(root,dispatch=lambda l:self.fail('duplicate level'))

    def test_interrupted_second_level_is_not_lost_from_resume_progress(self):
        now=datetime.now(timezone.utc)
        env=dict(REHEARSAL='0',CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='10')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,env):
            root=Path(tmp);atlas=root/'atlas';atlas.mkdir();(atlas/'campaigns').symlink_to(ATLAS/'campaigns',target_is_directory=True)
            (root/'inputs').mkdir();shutil.copytree(ROOT/s4.BUNDLE,root/s4.BUNDLE)
            s4.prepare(root,atlas);shutil.copyfile(ROOT/'STATE.json',root/'STATE.json')
            (root/'logs').mkdir();(root/'logs/current_server.json').write_text((ROOT/'results/droplet_logs/current_server.json').read_text())
            seen=[]
            def interrupt(level):
                seen.append(level)
                if level=='c8':raise RuntimeError('disconnect')
            def guard(root,plan,level,seconds,remaining):return dict(remaining=list(remaining),dropped=[])
            with patch.object(flow,'budget',side_effect=guard),self.assertRaisesRegex(RuntimeError,'disconnect'):flow.run(root,dispatch=interrupt)
            with patch.object(flow,'budget',side_effect=guard):flow.run(root,dispatch=seen.append)
            self.assertEqual(seen,['c16','c8','c8','c4','c1'])
            progress=json.loads((root/'results/session4/progress.json').read_text())
            self.assertEqual(progress['completed'][0]['decision']['remaining'],['c8','c4','c1'])


class SetupTests(unittest.TestCase):
    def test_weights_and_native_are_started_in_parallel_and_both_waited(self):
        barrier=threading.Barrier(2);finished=[]
        def work(name):
            barrier.wait(timeout=2);finished.append(name)
        setup.parallel(lambda:work('weights'),lambda:work('native'))
        self.assertCountEqual(finished,['weights','native'])
        with self.assertRaisesRegex(RuntimeError,'weights'):
            setup.parallel(lambda:(_ for _ in ()).throw(ValueError('weights')),lambda:finished.append('native2'))
        self.assertIn('native2',finished)

    def test_setup_only_pulls_vllm_and_records_timings(self):
        calls=[]
        def command(args,**kwargs):
            calls.append(args);return subprocess.CompletedProcess(args,0)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,VLLM_IMAGE='pinned-vllm',SCRATCH_DIR=tmp),patch.object(setup.subprocess,'run',side_effect=command),patch.object(setup,'run_cancellable',side_effect=lambda args,cancel,**kw:command(args,**kw)):
            root=Path(tmp);setup.setup(root,root)
            record=json.loads((root/'logs/setup_timings.json').read_text())
            self.assertEqual([c for c in calls if c[:2]==['docker','pull']],[['docker','pull','pinned-vllm']])
            download=next(c for c in calls if c[:2]==['docker','run'] and 'snapshot_download' in c[-1])
            self.assertFalse(any(c=='--user' or c.startswith('--device') or c=='--group-add' for c in download))
            self.assertIn('weights_download',record['steps']);self.assertIn('native_prepare',record['steps'])

    def test_level_has_one_ttft_bracket_across_retries_and_export_only_resume(self):
        source=(ROOT/'scripts/atlas_remote.sh').read_text()
        start=source.index('    elif [[ $action == _s4-level ]]; then')
        body=source[start:source.index('    elif [[ $action == _stop ]]',start)].split('then',1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'atlas').mkdir();sample=root/'raw/c4/samples.jsonl';sample.parent.mkdir(parents=True)
            stub=r"""
set -e
SESSION4=1;ROOT_DIR=$TEST_ROOT;ATLAS=$TEST_ROOT/atlas;RESULTS_DIR=$TEST_ROOT;CAMPAIGN=campaign;DB=$TEST_ROOT/db
preflight(){ :; }
queue(){ test "$SESSION4_LEVEL_SAMPLING" = 1; echo "queue $1" >> "$TEST_ROOT/calls"; }
node(){ echo export >> "$TEST_ROOT/calls"; }
python3(){
 if [[ $1 == - ]];then
   test -f "$2" && grep -q "${3:-after}" "$2";return
 elif [[ $1 == */sample_006.py ]];then
   echo "$5" >> "$2";echo "boundary $5" >> "$TEST_ROOT/calls"
 elif [[ $1 == */session4_retry_006.py && $5 == 1 ]];then
   echo "$ATLAS/campaign/c4-retry1.json"
 fi
}
set -- c4
"""
            env=dict(os.environ,TEST_ROOT=tmp)
            for _ in range(2):
                r=subprocess.run(['bash'],input=stub+body,env=env,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)
            lines=(root/'calls').read_text().splitlines()
            self.assertEqual(lines.count('boundary before'),1);self.assertEqual(lines.count('boundary after'),1)
            self.assertEqual(lines.count('queue campaign/c4.json'),2)
            self.assertEqual(lines.count('queue campaign/c4-retry1.json'),2)
            self.assertEqual(lines.count('export'),2)


class SummaryTests(unittest.TestCase):
    def test_matched_view_and_split_session_windows(self):
        row=json.loads((ROOT/'inputs/atlas-dry-p08/runs.json').read_text())['rows'][0]
        rows=[]
        for level in ('c1','c4'):
            for task in ('c18','c09','c28'):
                rows.append(dict(row,task=task,run_id=level+task,level=level,category='solved',solved_by_tests=True,
                                 started_at='2026-10-15T00:00:00Z',ended_at='2026-10-15T00:00:01Z',wall_s=1,study_session=3))
        rows[1].update(study_session=4,started_at='2026-10-16T00:00:00Z',ended_at='2026-10-16T00:00:02Z',wall_s=2)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'runs.json';p.write_text(json.dumps(dict(complete=True,scored=False,matched_tasks=['c18','c09'],rows=rows)))
            levels,normalized=summary.summarize([p],allow_fixtures=True)
            self.assertEqual(levels[0]['level_wall_s'],3)
            self.assertIsNone(levels[0]['engine_ttft_p50_s'])
            summary.write_matched(root,levels,normalized)
            import csv
            with (root/'matched_summary.csv').open() as f:view=list(csv.DictReader(f))
            self.assertEqual([r['runs'] for r in view],['2','2']);self.assertEqual([r['complete'] for r in view],['true','true'])
            self.assertIn('tokens_in_per_task',view[0])
            summary.write_csv(root/'runs.csv',normalized)
            csv_levels,csv_rows=summary.summarize([root/'runs.csv'],allow_fixtures=True)
            self.assertEqual(csv_rows[0]['matched_tasks'],['c18','c09'])
            self.assertEqual(csv_levels[0]['level_wall_s'],3)


if __name__=='__main__':unittest.main()
