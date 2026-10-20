"""ESC-001: diagnostics cannot turn a ready engine into a failed candidate."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import engine_metadata_006 as metadata


class MetadataTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'logs').mkdir()
        (root / 'logs/current_server.json').write_text(json.dumps(dict(engine='sglang', cfg='SD')))
        snapshot = root / 'hf/hub/models--Qwen--Qwen3.8-27B'
        (snapshot / 'refs').mkdir(parents=True)
        (snapshot / 'refs/main').write_text('rev')
        (snapshot / 'snapshots/rev').mkdir(parents=True)
        (snapshot / 'snapshots/rev/model.safetensors').write_bytes(b'fake weights')

    def test_all_diagnostics_fail_independently_and_preserve_ready_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'logs').mkdir()
            (root / 'logs/current_server.json').write_text('{"engine":"vllm"}')
            with patch.object(metadata.subprocess, 'run', side_effect=OSError('fake Docker failure')):
                result = metadata.collect(root, 'vllm', root, 'Qwen/Qwen3.8-27B')
            self.assertEqual(result['engine'], 'vllm')
            for field in ('image_id', 'model_revision', 'weights_sha256', 'engine_version', 'serve_help'):
                self.assertIsNone(result[field]); self.assertIn(field, result['provenance_errors'])
            self.assertEqual(json.loads((root/'logs/current_server.json').read_text()), result)

    def test_version_and_help_inherit_ready_server_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root); commands = []
            def fake(args, **kwargs):
                commands.append(args)
                if args[:2] == ['docker', 'inspect']:
                    return subprocess.CompletedProcess(args, 0, '[{"Image":"sha256:fixture"}]', '')
                if args[3:5] == ['python3', '-c']:
                    return subprocess.CompletedProcess(args, 0, '0.5.9\n', '')
                kwargs['stdout'].write('fake help\n')
                return subprocess.CompletedProcess(args, 0)
            with patch.object(metadata.subprocess, 'run', fake):
                result = metadata.collect(root, 'sglang', root, 'Qwen/Qwen3.8-27B')
            self.assertEqual(result['engine_version'], '0.5.9')
            self.assertEqual(result['provenance_errors'], {})
            self.assertTrue(result['weights_sha256']); self.assertEqual(result['model_revision'], 'rev')
            self.assertTrue(all(c[:3] == ['docker', 'exec', 'engine-server'] for c in commands[1:]))
            self.assertEqual(commands[-1][3:], metadata.help_command('sglang'))

    def test_metadata_and_pip_fallback_without_importing_engine(self):
        # Simulate an installed distribution, then force the pip-show fallback.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dist = root / 'sglang-1.2.3.dist-info'; dist.mkdir()
            (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: sglang\nVersion: 1.2.3\n')
            env = dict(os.environ, PYTHONPATH=tmp)
            r = subprocess.run([sys.executable, '-c', metadata.VERSION_CODE, 'sglang'], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout.strip(), '1.2.3')
            prelude = '''import importlib.metadata, subprocess
def absent(*a): raise importlib.metadata.PackageNotFoundError('fake')
importlib.metadata.version=absent
subprocess.run=lambda *a,**k: subprocess.CompletedProcess(a,0,'Name: sglang\\nVersion: 4.5.6\\n','')
'''
            r = subprocess.run([sys.executable, '-c', prelude + metadata.VERSION_CODE, 'sglang'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout.strip(), '4.5.6')
            self.assertNotIn('import sglang', metadata.VERSION_CODE)

    def test_help_failure_does_not_erase_successful_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            def fake(args, **kwargs):
                if args[1] == 'inspect': return subprocess.CompletedProcess(args, 0, '[{"Image":"image"}]', '')
                if args[3:5] == ['python3', '-c']: return subprocess.CompletedProcess(args, 0, '1.0\n', '')
                kwargs['stdout'].write('fake help failed\n'); return subprocess.CompletedProcess(args, 1)
            with patch.object(metadata.subprocess, 'run', fake):
                result = metadata.collect(root, 'vllm', root, 'Qwen/Qwen3.8-27B')
            self.assertEqual(result['engine_version'], '1.0'); self.assertIsNone(result['serve_help'])
            self.assertIn('serve_help', result['provenance_errors'])
            self.assertIn('fake help failed', (root / 'logs/vllm_serve_help.txt').read_text())

    def test_ready_launch_survives_collector_failure(self):
        source = (ROOT / 'scripts/atlas_remote.sh').read_text()
        serve = source[source.index('stop_server() {'):source.index('\nqueue() {')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'scripts').mkdir(); (root / 'logs').mkdir()
            for name in ('stop_engine.sh', 'serve_engine.sh'):
                p = root / 'scripts' / name; p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
            (root / 'scripts/engine_metadata_006.py').write_text('raise SystemExit(47)\n')
            env = dict(os.environ, ROOT_DIR=tmp, LOG_DIR=str(root/'logs'), REHEARSAL='0', MODEL='fake')
            r = subprocess.run(['bash', '-e'], input=serve + '\nserve vllm\n', env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_provenance_write_failure_preserves_ready_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'logs').mkdir()
            path = root / 'logs/current_server.json'; original = '{"engine":"sglang"}'
            path.write_text(original)
            with patch.object(metadata.subprocess, 'run', side_effect=OSError('fake Docker failure')), \
                    patch.object(metadata.os, 'replace', side_effect=OSError('fake write failure')):
                with self.assertRaisesRegex(OSError, 'fake write failure'):
                    metadata.collect(root, 'sglang', root, 'Qwen/Qwen3.8-27B')
            self.assertEqual(path.read_text(), original)
            self.assertEqual({p.name for p in (root / 'logs').iterdir()}, {'current_server.json', 'sglang_serve_help.txt'})


class SyncTests(unittest.TestCase):
    def test_sync_uses_atlas_root_even_if_legacy_config_disagrees(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'scripts').mkdir(); bin = root / 'bin'; bin.mkdir()
            shutil.copyfile(ROOT / 'scripts/sync_results.sh', root / 'scripts/sync_results.sh')
            (root / 'config.env').write_text('DROPLET_IP=fixture\nATLAS_REMOTE_ROOT=<HOME>/custom-study\nREMOTE_REPO_DIR=<HOME>/wrong\n')
            calls = root / 'calls'
            for name, body in [('rsync', 'exit 0'), ('ssh', 'echo 0')]:
                p = bin / name
                p.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n' + body + '\n'); p.chmod(0o755)
            r = subprocess.run(['bash', str(root/'scripts/sync_results.sh')], env=dict(os.environ, PATH=str(bin)+':'+os.environ['PATH'], CALLS=str(calls)), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('<HOME>/custom-study/results', calls.read_text())
            self.assertNotIn('<HOME>/wrong', calls.read_text())


class BootstrapMetadataTests(unittest.TestCase):
    def test_missing_version_commands_record_null_and_errors(self):
        source = (ROOT / 'scripts/atlas_bootstrap_006.sh').read_text()
        body = source.split("<<'PY' || true\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'versions.json'
            prelude = '''import subprocess
def missing(*a, **k): raise OSError("fake version command absent")
subprocess.check_output=missing
'''
            r = subprocess.run([sys.executable, '-c', prelude + body, str(output), '/fake/node'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(output.read_text())
            for field in ('node', 'npm', 'tmux', 'groups', 'docker', 'buildx', 'python'):
                self.assertIsNone(data[field])
            self.assertEqual(len(data['provenance_errors']), 7)


if __name__ == '__main__':
    unittest.main()
