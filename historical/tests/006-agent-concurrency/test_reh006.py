"""Session-5 grading completion, strict checkpoint recovery, and Mac preflight."""
import copy
from datetime import datetime,timedelta,timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'inputs/reh006'
sys.path.insert(0,str(ROOT/'scripts'))
import session4_recover_006 as recover


def fixture_root(root):
    scope=root/'results/session4';scope.mkdir(parents=True)
    for src,dest in [('session6_resume_before.json','resume.json'),('session5_pending_complete.json','pending_native.json')]:shutil.copyfile(FIXTURE/src,scope/dest)
    for name in ('progress.json','execution-image-map.json'):shutil.copyfile(ROOT/'results/session4'/name,scope/name)
    report=root/'results/atlas/scored/live/c16/runs.json';report.parent.mkdir(parents=True);shutil.copyfile(FIXTURE/'session5_c16_complete.json',report)
    # Small tar payload retains the exact real pre-grade export; real archive is
    # exercised separately by the complete preflight integration case.
    with tarfile.open(scope/'resume_data.tar.gz','w:gz') as t:
        d=tarfile.TarInfo('data');d.type=tarfile.DIRTYPE;d.mode=0o700;t.addfile(d)
        body=(FIXTURE/'c16_pending.json').read_bytes();m=tarfile.TarInfo('data/rocm-recipes-006/live/c16/runs.json');m.size=len(body);m.mode=0o600;t.addfile(m,io.BytesIO(body))
    spec=json.loads((scope/'resume.json').read_text());spec['files']['resume_data.tar.gz']=recover.sha(scope/'resume_data.tar.gz');recover.save(scope/'resume.json',spec)
    return scope


class CompletionTests(unittest.TestCase):
    def test_real_session5_transition_recheckpoint_restore_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=fixture_root(root);original=json.loads((scope/'resume.json').read_text())
            with self.assertRaisesRegex(ValueError,'checkpoint changed: pending_native'):recover.verify_checkpoint(root)
            recover.recheckpoint(root,FIXTURE/'pending_before.json')
            current=recover.verify_checkpoint(root)
            for name in ['resume_data.tar.gz','progress.json','execution-image-map.json']:self.assertEqual(original['files'][name],current['files'][name])
            recover.recheckpoint(root)
            atlas=root/'atlas';atlas.mkdir();recover.restore(root,atlas)
            report=json.loads((atlas/'data/rocm-recipes-006/live/c16/runs.json').read_text())
            self.assertEqual(report,json.loads((FIXTURE/'session5_c16_complete.json').read_text()))
            row=next(r for r in report['rows'] if r['run_id'].endswith('1162'))
            self.assertEqual(row['category'],'infra_error');self.assertTrue(row['excluded']);self.assertFalse(row['native_grade_pending'])
            self.assertEqual(report['pending_native_grades'],0)

    def test_reverse_and_unrelated_registry_changes_rejected(self):
        previous=json.loads((FIXTURE/'pending_before.json').read_text());complete=json.loads((FIXTURE/'session5_pending_complete.json').read_text())
        with self.assertRaises(ValueError):recover.completed_transition(complete,previous)
        for mutation in ['tokens','proof','extra','host']:
            changed=copy.deepcopy(complete)
            if mutation=='tokens':changed['runs'][0]['row']['tokens_in']+=1
            elif mutation=='proof':changed['runs'][0]['proof']['trace_sha256']='changed'
            elif mutation=='extra':changed['runs'][0]['anything']='changed'
            else:changed['runs'][0]['grading_host']['platform']='linux/arm64'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):recover.completed_transition(previous,changed)

    def test_unrelated_files_and_report_measurements_stay_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=fixture_root(root);checkpoint=(scope/'resume.json').read_bytes()
            p=scope/'progress.json';original=p.read_bytes();p.write_bytes(original+b' ')
            with self.assertRaisesRegex(ValueError,'checkpoint changed: progress'):recover.recheckpoint(root,FIXTURE/'pending_before.json')
            p.write_bytes(original)
            report=root/'results/atlas/scored/live/c16/runs.json';changed=json.loads(report.read_text());changed['rows'][-1]['wall_s']+=1;recover.save(report,changed)
            with self.assertRaisesRegex(ValueError,'execution measurements'):recover.recheckpoint(root,FIXTURE/'pending_before.json')
            self.assertEqual((scope/'resume.json').read_bytes(),checkpoint)
            self.assertFalse((scope/'resume_c16.json').exists())


class PreflightTests(unittest.TestCase):
    def test_controller_checks_preflight_before_ssh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'contacted';bin=root/'bin';bin.mkdir()
            for name in ('ssh','scp','rsync'):
                p=bin/name;p.write_text('#!/bin/sh\necho contacted >> '+str(marker)+'\nexit 90\n');p.chmod(0o755)
            env=self.environment();env.update(SESSION4='1',REHEARSAL='0',SESSION_CAP_HOURS='7',PATH=str(bin)+':'+env['PATH'])
            for action in ('setup','session4'):
                result=subprocess.run(['bash',str(ROOT/'scripts/atlas_remote.sh'),action],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0);self.assertIn('cap=10',result.stderr);self.assertFalse(marker.exists())

    def environment(self):
        return {k:v for k,v in os.environ.items() if k not in ('CREATED_AT','HARD_DEADLINE','SESSION_CAP_HOURS','ATLAS_SOURCE')}

    def config(self,path,future=False):
        created=datetime.now(timezone.utc)+(timedelta(hours=1) if future else -timedelta(minutes=1))
        text=(ROOT/'config.env').read_text();values={'CREATED_AT':created.isoformat(),'HARD_DEADLINE':(created+timedelta(hours=10.5)).isoformat(),'SESSION_CAP_HOURS':'10'}
        path.write_text('\n'.join(key+'='+values[key] if (key:=line.split('=',1)[0]) in values else line for line in text.splitlines())+'\n')

    def run_preflight(self,config,root=ROOT,env=None):
        return subprocess.run(['bash',str(ROOT/'scripts/preflight_006.sh'),'--config',str(config),'--root',str(root)],env=env or self.environment(),capture_output=True,text=True)

    def test_session5_cap7_and_future_created_are_rejected(self):
        result=self.run_preflight(FIXTURE/'session5.env')
        self.assertNotEqual(result.returncode,0);self.assertIn('cap=10',result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'future.env';self.config(config,future=True);result=self.run_preflight(config)
            self.assertNotEqual(result.returncode,0);self.assertIn('CREATED_AT is in the future',result.stderr)

    def test_prefixed_session6_checkpoint_fails_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=fixture_root(root)
            (root/'STATE.json').symlink_to(ROOT/'STATE.json');(root/'inputs').symlink_to(ROOT/'inputs',target_is_directory=True)
            logs=root/'results/droplet_logs';logs.mkdir();(logs/'current_server.json').symlink_to(ROOT/'results/droplet_logs/current_server.json')
            config=root/'valid.env';self.config(config);result=self.run_preflight(config,root)
            self.assertNotEqual(result.returncode,0);self.assertIn('checkpoint changed: pending_native.json',result.stderr)

    def test_current_state_passes_without_ssh_cloud_or_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'valid.env';self.config(config);bin=root/'bin';bin.mkdir();marker=root/'forbidden'
            for command in ('ssh','scp','rsync','docker','doctl','curl'):
                p=bin/command;p.write_text('#!/bin/sh\necho forbidden >> '+str(marker)+'\nexit 90\n');p.chmod(0o755)
            env=self.environment();env['PATH']=str(bin)+':'+env['PATH']
            result=self.run_preflight(config,env=env)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,'PREFLIGHT OK\n');self.assertFalse(marker.exists())


if __name__=='__main__':unittest.main()
