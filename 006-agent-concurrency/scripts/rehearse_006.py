#!/usr/bin/env python3
"""Drive the complete CPU rehearsal on an EXISTING Ubuntu x86_64 SSH host."""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(dry=False, session4=False):
    if session4:os.environ["SESSION4"]="1"
    target = os.environ.get('ATLAS_SSH_TARGET', '')
    remote = os.environ.get('ATLAS_REMOTE_ROOT', '')
    if os.environ.get('REHEARSAL') != '1' or not re.fullmatch(r'root@[A-Za-z0-9.-]+', target) or not re.fullmatch(r'/home/atlas/[A-Za-z0-9_-]+-rehearsal', remote):
        raise ValueError('Set REHEARSAL=1, ATLAS_SSH_TARGET=root@CPU_HOST and a fresh ATLAS_REMOTE_ROOT ending in -rehearsal')
    wrapper = ['bash', str(ROOT/'scripts/atlas_remote.sh')]

    def command(args):
        print('$ '+shlex.join(args), flush=True)
        subprocess.run(args, cwd=ROOT, check=True)

    def job(*args):
        command(wrapper+(['--dry-run'] if dry else [])+list(args))
        if dry:
            return
        name = '-'.join(args) if args[0] in ('serve', 'run') else args[0]
        deadline = time.monotonic()+float(os.environ.get('REHEARSAL_JOB_TIMEOUT_S', '10800'))
        # Read the JSON file, never instantiate Store/SQLite as root for diagnostics.
        script = f"""import json,subprocess
s=json.load(open({remote+'/results/rehearsal/STATE.json'!r}))
busy=subprocess.run(['runuser','-u','atlas','--','tmux','has-session','-t','rocm006-atlas'],capture_output=True).returncode==0
print(json.dumps(dict(job=s.get('atlas',{{}}).get('jobs',{{}}).get({name!r},{{}}),busy=busy)))
"""
        while time.monotonic() < deadline:
            result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', target,
                                     'python3 -c '+shlex.quote(script)], check=True, capture_output=True, text=True)
            status = json.loads(result.stdout)
            state = status['job'].get('status')
            if state in ('FAILED', 'DONE') and not status['busy']:
                if state != 'DONE' or status['job'].get('exit_code') != 0:
                    raise ValueError('Remote job failed: '+name+'; inspect its rehearsal log before retrying')
                return
            time.sleep(5)
        raise ValueError('Timed out waiting for '+name+'; job was left intact')

    command(['bash',str(ROOT/'scripts/rehearsal_prep.sh')]+(['--dry-run'] if dry else []))
    job('setup')
    if not dry:
        path=remote+'/results/rehearsal/logs/bootstrap_versions.json'
        result=subprocess.run(['ssh',target,'cat '+shlex.quote(path)],check=True,capture_output=True,text=True)
        versions=json.loads(result.stdout)
        if versions.get('docker')!='Docker version 29.8.2, build 7fc2dff' or versions.get('buildx')!='github.com/docker/buildx v0.37.1 0b265a9f62db554fa9aba6dd19e1bd5704bc7d8a':
            raise ValueError('atlas bootstrap Docker/buildx differs from GPU baseline; stop before probe')
    if session4:
        job('session4')
        command(wrapper+(['--dry-run'] if dry else [])+['sync-grading'])
        if dry:
            print('Session 4 CPU rehearsal: c16 -> c8 -> c4 -> c1; no probe or 5b. Then sync and summarize the matched ten-task view in results/rehearsal.')
        else:
            command(['bash',str(ROOT/'scripts/sync_results.sh')])
            print('Session 4 CPU queues finished; use the normal Mac-grade/finalize flow. No claims pause the queues.')
        return
    job('probe')
    engine = 'sglang'
    if not dry:
        path = remote+'/results/rehearsal/notes/engine_choice.json'
        result = subprocess.run(['ssh', target, 'cat '+shlex.quote(path)], check=True, capture_output=True, text=True)
        choice = json.loads(result.stdout)
        if choice.get('rehearsal') is not True:
            raise ValueError('Expected rehearsal choice')
        engine = choice['engine']
    job('serve', engine)
    for level in ('c1', 'c4', 'c8', 'c16'):
        job('run', level)
    job('phase3b')
    if dry:
        command(wrapper+['--dry-run', 'sync-grading'])
        print('Then sync_results.sh and summarize_006.py --allow-fixtures --live into results/rehearsal/live; no commands dispatched.')
        return
    command(wrapper+['sync-grading'])
    command(['bash',str(ROOT/'scripts/sync_results.sh')])
    scope = ROOT/'results/rehearsal'
    state = json.loads((scope/'STATE.json').read_text())
    if state['steps']['P3b']['status'] != 'DONE':
        raise ValueError('Kx was skipped/blocked; inspect rehearsal notes/kx_report.md')
    exports = [scope/f'atlas/main/live/{level}/runs.json' for level in ('c1','c4','c8','c16')]
    samples = [scope/f'raw/{level}/samples.jsonl' for level in ('c1','c4','c8','c16')]
    command(['python3',str(ROOT/'scripts/summarize_006.py'),*map(str,exports), '--allow-fixtures','--live',
             '--output-dir',str(scope/'live'),'--samples',*map(str,samples)])
    counts = {p.stem:json.loads(p.read_text()) for p in sorted((scope/'grading/counts').glob('*.json'))}
    print('Mac handoff counts (queues completed): '+json.dumps(counts,indent=2))
    print('Rehearsal execution complete. Final export still requires the normal Mac classify + semantic audit for every pending request; see notes/rehearsal_006.md.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--session4', action='store_true', help='Amendment A: vLLM, descending queues, no probe/5b')
    try:
        args=parser.parse_args()
        run(args.dry_run,args.session4)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
