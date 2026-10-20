#!/usr/bin/env python3
"""Best-effort engine provenance after readiness; never an engine eligibility gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

# No engine import: package imports can initialize ROCm or lack __version__.
# This exact program is also exercised in the off-GPU pinned-image check.
VERSION_CODE = '''import importlib.metadata, subprocess, sys
try:
    value = importlib.metadata.version(sys.argv[1])
except Exception as error:
    print("importlib.metadata: " + str(error), file=sys.stderr)
    result = subprocess.run([sys.executable, "-m", "pip", "show", sys.argv[1]],
                            capture_output=True, text=True, check=True, timeout=30)
    value = next((line.split(":", 1)[1].strip() for line in result.stdout.splitlines()
                  if line.startswith("Version:")), None)
    if not value:
        raise RuntimeError("pip show returned no Version field")
print(value)
'''


def help_command(engine):
    return ['vllm', 'serve', '--help'] if engine == 'vllm' else ['python3', '-m', 'sglang.launch_server', '--help']


def checked(args, timeout=60):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[:3]} exited {result.returncode}: {result.stderr[-4000:]}')
    return result


def collect(root, engine, scratch, model):
    path = root / 'logs/current_server.json'
    errors = {}
    try:
        record = json.loads(path.read_text())
    except Exception as error:
        record = {}
        errors['current_server'] = f'{type(error).__name__}: {error}'
    record['provenance_errors'] = errors

    def attempt(field, operation):
        try:
            record[field] = operation()
        except Exception as error:
            record[field] = None
            errors[field] = f'{type(error).__name__}: {error}'

    attempt('image_id', lambda: json.loads(checked(['docker', 'inspect', 'engine-server']).stdout)[0]['Image'])
    cache = scratch / 'hf/hub' / ('models--' + model.replace('/', '--'))
    def revision():
        value = (cache / 'refs/main').read_text().strip()
        if not value:
            raise ValueError('Empty cached model revision')
        return value
    attempt('model_revision', revision)

    def weights():
        if not record['model_revision']:
            raise ValueError('Model revision unavailable')
        files = sorted((cache / 'snapshots' / record['model_revision']).glob('*.safetensors'))
        if not files:
            raise ValueError('No BF16 safetensors found for provenance')
        hashes = {}
        for file in files:
            digest = hashlib.sha256()
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)
            hashes[file.name] = digest.hexdigest()
        return hashes
    attempt('weights_sha256', weights)

    def version():
        # docker exec inherits every device mapping/IPC/security/environment option
        # from the real, ready server. In particular vLLM never runs in a bare container.
        result = checked(['docker', 'exec', 'engine-server', 'python3', '-c', VERSION_CODE, engine])
        if result.stderr.strip():
            record.setdefault('provenance_warnings', {})['engine_version'] = result.stderr.strip()
        value = result.stdout.strip()
        if not value:
            raise ValueError('Empty package version')
        return value
    attempt('engine_version', version)

    def help_text():
        # Help imports may require ROCm too. Use the running server's exact context.
        target = root / 'logs' / f'{engine}_serve_help.txt'
        command = ['docker', 'exec', 'engine-server', *help_command(engine)]
        with target.open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(f'Help exited {result.returncode}; output: {target}')
        return str(target.relative_to(root))
    attempt('serve_help', help_text)
    # Keep the ready server's identity intact even if provenance cannot be written.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps(record, indent=2) + '\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if errors:
        print('Non-fatal provenance errors: ' + json.dumps(errors), file=sys.stderr)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--engine', choices=['vllm', 'sglang'], required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--model', default='Qwen/Qwen3.8-27B')
    args = parser.parse_args()
    try:
        collect(args.root, args.engine, args.scratch, args.model)
    except Exception as error:
        # Even an unwritable provenance file must not reject a ready engine.
        print(f'Non-fatal provenance collection error: {type(error).__name__}: {error}', file=sys.stderr)
