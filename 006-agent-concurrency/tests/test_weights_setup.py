"""REH-004: root image Python, shared cache layout, and early setup failure."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import session4_setup_006 as setup


class WeightsSetupTests(unittest.TestCase):
    def test_root_commands_share_preflight_flags_and_cache_mount(self):
        commands=setup.weights_commands('pinned-vllm',Path('/mnt/scratch/hf'),1000,1000)
        for name in ('weights_preflight','weights_download','weights_chown'):
            command=commands[name]
            self.assertFalse(any(arg.startswith(('--user','--device','--group-add')) for arg in command))
            self.assertIn('HF_HOME=/hf',command)
            self.assertEqual(command[command.index('-v')+1],'/mnt/scratch/hf:/hf')
            self.assertEqual(command[command.index('--entrypoint')+2],'pinned-vllm')
        preflight=commands['weights_preflight'];download=commands['weights_download']
        self.assertEqual(preflight[:-1],download[:-1])
        self.assertEqual(preflight[-1],'import huggingface_hub, sys; print(huggingface_hub.__version__, sys.prefix)')
        self.assertEqual(commands['weights_chown'][-5:],['chown','pinned-vllm','-R','1000:1000','/hf'])
        self.assertIn('/hf/hub/models--Qwen--Qwen3.8-27B/snapshots/'+setup.REVISION,download[-1])

    def test_host_cache_verification_rejects_missing_snapshot_and_wrong_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'hf';model=cache/'hub/models--Qwen--Qwen3.8-27B'
            command=setup.weights_commands('pinned-vllm',cache,1000,1000)['weights_verify']
            def verify():return subprocess.run(command,capture_output=True,text=True).returncode
            self.assertNotEqual(verify(),0)
            (model/'snapshots'/setup.REVISION).mkdir(parents=True)
            (model/'refs').mkdir();ref=model/'refs/main';ref.write_text('wrong-revision')
            self.assertNotEqual(verify(),0)
            ref.write_text(setup.REVISION)
            self.assertEqual(verify(),0)

    def test_preflight_precedes_parallel_work_and_download_chown_verify_order(self):
        calls=[]
        def command(args,**kwargs):
            calls.append(args);return subprocess.CompletedProcess(args,0)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,VLLM_IMAGE='pinned-vllm',SCRATCH_DIR=tmp),patch.object(setup.subprocess,'run',side_effect=command),patch.object(setup,'run_cancellable',side_effect=lambda args,cancel,**kw:command(args,**kw)):
            root=Path(tmp);setup.setup(root,root)
            record=json.loads((root/'logs/setup_timings.json').read_text())
            names={name: calls.index(step['command']) for name,step in record['steps'].items()}
            self.assertLess(names['weights_preflight'],names['weights_download'])
            self.assertLess(names['weights_preflight'],names['native_prepare'])
            self.assertLess(names['weights_download'],names['weights_chown'])
            self.assertLess(names['weights_chown'],names['weights_verify'])
            self.assertEqual(record['steps']['weights_preflight']['exit_code'],0)
            self.assertIn('seconds',record['steps']['weights_preflight'])

    def test_failed_preflight_never_starts_native_or_weights(self):
        calls=[]
        def command(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,1 if 'huggingface_hub.__version__' in args[-1] else 0)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,VLLM_IMAGE='pinned-vllm',SCRATCH_DIR=tmp),patch.object(setup.subprocess,'run',side_effect=command),patch.object(setup,'run_cancellable') as native:
            root=Path(tmp)
            with self.assertRaisesRegex(RuntimeError,'weights_preflight failed'):setup.setup(root,root)
            native.assert_not_called()
            record=json.loads((root/'logs/setup_timings.json').read_text())
            self.assertEqual(record['steps']['weights_preflight']['exit_code'],1)
            self.assertNotIn('weights_download',record['steps'])
            self.assertNotIn('proxy_build',record['steps'])

    def test_failed_weights_stops_running_native_before_chown_finishes(self):
        stopped=threading.Event();real_run=setup.run_cancellable;calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);started=root/'native_started'
            def command(args,**kwargs):
                calls.append(args)
                if 'snapshot_download' in args[-1]:
                    deadline=time.monotonic()+3
                    while not started.exists() and time.monotonic()<deadline:time.sleep(0.01)
                    self.assertTrue(started.exists(),'native prepare did not start')
                    return subprocess.CompletedProcess(args,1)
                if '--entrypoint' in args and args[args.index('--entrypoint')+1]=='chown':
                    self.assertTrue(stopped.wait(3),'weights failure did not cancel native promptly')
                return subprocess.CompletedProcess(args,0)
            def native(args,cancel,**kwargs):
                self.assertIn('prepare-host',args)
                result=real_run([sys.executable,'-c',f'from pathlib import Path; import time; Path({str(started)!r}).touch(); time.sleep(30)'],cancel,**kwargs)
                stopped.set()
                return result
            with patch.dict(os.environ,VLLM_IMAGE='pinned-vllm',SCRATCH_DIR=tmp),patch.object(setup.subprocess,'run',side_effect=command),patch.object(setup,'run_cancellable',side_effect=native):
                began=time.monotonic()
                with self.assertRaisesRegex(RuntimeError,'weights_download failed'):setup.setup(root,root)
                self.assertLess(time.monotonic()-began,5)
            record=json.loads((root/'logs/setup_timings.json').read_text())
            self.assertEqual(record['steps']['weights_download']['exit_code'],1)
            self.assertTrue(record['steps']['native_prepare']['cancelled'])
            self.assertNotEqual(record['steps']['native_prepare']['exit_code'],0)
            self.assertEqual(record['steps']['weights_chown']['exit_code'],0)
            self.assertNotIn('native_check',record['steps'])
            self.assertNotIn('proxy_build',record['steps'])

    def test_cancelled_native_does_not_launch(self):
        cancel=threading.Event();cancel.set()
        with patch.object(setup.subprocess,'Popen') as process:
            result=setup.run_cancellable(['node','unused'],cancel)
        process.assert_not_called();self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
