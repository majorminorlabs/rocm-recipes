#!/usr/bin/env python3
"""ESC-001 evooffice check. Run only in the dedicated workspace with its pull ledger.

No inference, model downloads, pruning, or pre-existing container/image mutation.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from engine_metadata_006 import VERSION_CODE, help_command


def run(workspace):
    ledger = json.loads((workspace / 'ledger.json').read_text())
    prefix = workspace.name.lower()
    reports = []
    ledger['volumes_before'] = subprocess.check_output(['docker', 'volume', 'ls', '-q'], text=True).splitlines()
    def command(name, image, args, timeout=180):
        container = prefix + '-' + name
        cmd = ['docker', 'run', '--rm', '--name', container, '--label', 'rocm006.esc001=' + prefix,
               '--network', 'none', '--ipc=host', '--shm-size', '16g', '--security-opt', 'seccomp=unconfined',
               '--group-add', 'video', '-e', 'HF_HUB_OFFLINE=1',
               *(['--cap-add', 'SYS_PTRACE'] if name.startswith('sglang') else ['-e', 'VLLM_ROCM_USE_AITER=1']),
               '--entrypoint', args[0], image, *args[1:]]
        started = time.time()
        report = dict(name=name, command=cmd, started_at_unix=started)
        try:
            result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
            report.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
        except subprocess.TimeoutExpired as error:
            report.update(exit_code=None, error=str(error), stdout=str(error.stdout), stderr=str(error.stderr))
        finally:
            # A timed-out Docker client can leave its container alive. Verify our
            # exact label before removing only the named container we created.
            inspect = subprocess.run(['docker', 'inspect', container], text=True, capture_output=True)
            if inspect.returncode == 0:
                data = json.loads(inspect.stdout)[0]
                if data['Config']['Labels'].get('rocm006.esc001') == prefix:
                    report['cleanup_container'] = subprocess.run(['docker', 'rm', '-f', '-v', container], text=True, capture_output=True).returncode
            report['elapsed_s'] = time.time() - started
            reports.append(report)
            (workspace / 'checks.json').write_text(json.dumps(reports, indent=2) + '\n')
        return report

    try:
        for engine, entry in ledger['images'].items():
            image = entry['reference']
            inspect = subprocess.run(['docker', 'image', 'inspect', image], text=True, capture_output=True, check=True)
            entry['image_inspect'] = json.loads(inspect.stdout)
            name = prefix + '-' + engine + '-inspect'
            create = ['docker', 'create', '--name', name, '--label', 'rocm006.esc001=' + prefix,
                      '--entrypoint', 'python3', image, '-c', 'pass']
            created = subprocess.run(create, text=True, capture_output=True, check=True)
            try:
                inspected = subprocess.run(['docker', 'inspect', name], text=True, capture_output=True, check=True)
                reports.append(dict(name=engine + '-container-inspect', create_command=create, command=['docker', 'inspect', name],
                                    stdout=inspected.stdout, stderr=inspected.stderr, image_id=json.loads(inspected.stdout)[0]['Image'], exit_code=0))
            finally:
                # Exact newly-created ID; never removes a pre-existing named server.
                subprocess.run(['docker', 'rm', '-v', created.stdout.strip()], check=True, capture_output=True)
            command(engine + '-version', image, ['python3', '-c', VERSION_CODE, engine])
            # Exercise the actual fallback against the real pip/distribution too.
            forced = '''import importlib.metadata
def absent(*a): raise importlib.metadata.PackageNotFoundError("forced fallback check")
importlib.metadata.version=absent
''' + VERSION_CODE
            command(engine + '-pip-fallback', image, ['python3', '-c', forced, engine])
            command(engine + '-pip-show', image, ['python3', '-m', 'pip', 'show', engine])
            if engine == 'sglang':
                command('sglang-help', image, help_command(engine))
                command('sglang-tokenizer-import', image, ['python3', '-c', 'from transformers import AutoTokenizer; print(AutoTokenizer.__name__)'])
        ledger['untested_gpu_commands'] = [
            'vllm serve --help inside the ready ROCm server (requires /dev/kfd and /dev/dri)',
            'Actual engine startup/readiness, runtime docker exec, tool/cache smoke and c8 probe',
        ]
        ledger['untested_cache_commands'] = ['Real cached-model revision/weight hashing and W-MP generation (no model cache on evooffice)']
    finally:
        for engine, entry in ledger['images'].items():
            if not entry['existed_before']:
                result = subprocess.run(['docker', 'image', 'rm', entry['reference']], text=True, capture_output=True)
                entry['cleanup'] = dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
                entry['absent_after_cleanup'] = subprocess.run(['docker', 'image', 'inspect', entry['reference']], capture_output=True).returncode != 0
        ledger['volumes_after'] = subprocess.check_output(['docker', 'volume', 'ls', '-q'], text=True).splitlines()
        ledger['new_volumes_remaining'] = sorted(set(ledger['volumes_after']) - set(ledger['volumes_before']))
        ledger['preexisting_volumes_retained'] = set(ledger['volumes_before']) <= set(ledger['volumes_after'])
        ledger['containers_after'] = subprocess.check_output(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], text=True).splitlines()
        ledger['preexisting_containers_retained'] = set(ledger['containers_before']) <= set(ledger['containers_after'])
        ledger['new_containers_remaining'] = sorted(set(ledger['containers_after']) - set(ledger['containers_before']))
        (workspace / 'ledger.json').write_text(json.dumps(ledger, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    run(parser.parse_args().workspace)
