#!/usr/bin/env python3
"""Timed session-4 setup: only vLLM; weights overlap native task-image preparation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

MODEL = 'Qwen/Qwen3.8-27B'
REVISION = '1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0'


def weights_commands(image, cache, uid, gid):
    # Root is the pinned image's working Python environment; no GPU is needed.
    container = ['docker','run','--rm','--ipc=host','--shm-size','16g',
                 '--security-opt','seccomp=unconfined','-e','HF_HOME=/hf',
                 '-v',str(cache)+':/hf']
    snapshot = Path('hub')/('models--'+MODEL.replace('/','--'))/'snapshots'/REVISION
    ref = snapshot.parent.parent/'refs/main'
    download = (
        'from huggingface_hub import snapshot_download; from pathlib import Path; '
        f'p=Path(snapshot_download(repo_id={MODEL!r}, revision={REVISION!r})); '
        f'expected=Path({str(Path("/hf")/snapshot)!r}); '
        'assert p == expected and expected.is_dir(), (p, expected); '
        f'r=Path({str(Path("/hf")/ref)!r}); '
        f'r.parent.mkdir(parents=True,exist_ok=True); r.write_text({REVISION!r}); '
        f'assert r.read_text().strip() == {REVISION!r}; print(p)'
    )
    return {
        'weights_preflight': container+['--entrypoint','python3',image,'-c',
            'import huggingface_hub, sys; print(huggingface_hub.__version__, sys.prefix)'],
        'weights_download': container+['--entrypoint','python3',image,'-c',download],
        'weights_chown': container+['--entrypoint','chown',image,'-R',f'{uid}:{gid}','/hf'],
        'weights_verify': ['python3','-c','from pathlib import Path; '
            f'p=Path({str(cache/snapshot)!r}); assert p.is_dir(), p; '
            f'r=Path({str(cache/ref)!r}); assert r.read_text().strip() == {REVISION!r}, r; print(p)'],
    }


def run_cancellable(command, cancel, **kwargs):
    if cancel.is_set():
        return subprocess.CompletedProcess(command,-signal.SIGTERM)
    # Kill the native CLI and its child build clients, never unrelated processes.
    with subprocess.Popen(command,start_new_session=True,**kwargs) as process:
        while True:
            try:
                code=process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if not cancel.is_set():
                    continue
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    code=process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    code=process.wait()
                break
    return subprocess.CompletedProcess(command,code)


def parallel(weights, native, cancel_native=lambda: None):
    # Weights is awaited first so its failure immediately stops native work.
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(f) for f in (weights,native)]
        for job in jobs:
            try:
                job.result()
            except Exception as error:
                if job is jobs[0]:
                    cancel_native()
                errors.append(str(error))
    if errors:
        raise RuntimeError('; '.join(errors))


def setup(root, atlas, rehearsal=False):
    context = root/'results/rehearsal' if rehearsal else root
    logs = context/'logs'; logs.mkdir(parents=True,exist_ok=True)
    timing_path=logs/'setup_timings.json'
    timings = json.loads(timing_path.read_text()) if timing_path.exists() else dict(started_at=datetime.now(timezone.utc).isoformat(), rehearsal=rehearsal, steps={})
    began = time.monotonic()
    cancel_native = threading.Event()

    def step(name, command, cwd=atlas, cancellable=False):
        start=time.monotonic();start_utc=datetime.now(timezone.utc).isoformat()
        with (logs/('setup_'+name+'.log')).open('w') as output:
            if cancellable:
                result=run_cancellable(command,cancel_native,cwd=cwd,stdout=output,stderr=subprocess.STDOUT)
            else:
                result=subprocess.run(command,cwd=cwd,stdout=output,stderr=subprocess.STDOUT)
        timings['steps'][name]=dict(started_at=start_utc,ended_at=datetime.now(timezone.utc).isoformat(),seconds=time.monotonic()-start,exit_code=result.returncode,command=command)
        if cancellable and cancel_native.is_set():
            timings['steps'][name]['cancelled']=True
            raise RuntimeError(name+' cancelled after weights failure; see '+str(logs/('setup_'+name+'.log')))
        if result.returncode:
            raise RuntimeError(name+' failed; see '+str(logs/('setup_'+name+'.log')))

    def native():
        step('native_prepare',['node','runner/cli.ts','prepare-host','data/rocm-recipes-006-native-session4','--prefix','atlas-rocm006-native-session4'],cancellable=not rehearsal)
        step('native_check',['node','runner/cli.ts','check-host','data/rocm-recipes-006-native-session4/image-map.json'],cancellable=not rehearsal)
        if not rehearsal and (root/'results/session4/pending_native.json').exists():
            step('pending_native',['node',str(root/'scripts/session4_retained_006.ts'),'grade',str(root),str(atlas)],cancellable=True)

    try:
        step('npm_ci',['npm','ci'])
        if rehearsal:
            def weights():
                timings['steps']['weights_download']=dict(seconds=0,exit_code=0,skipped='CPU rehearsal: fake vLLM, no weights or GPU images')
        else:
            image=os.environ['VLLM_IMAGE']
            step('vllm_pull',['docker','pull',image])
            cache=Path(os.environ.get('SCRATCH_DIR','/mnt/scratch'))/'hf'
            cache.mkdir(parents=True,exist_ok=True)
            commands=weights_commands(image,cache,os.getuid(),os.getgid())
            step('weights_preflight',commands['weights_preflight'])
            def weights():
                try:
                    step('weights_download',commands['weights_download'])
                except Exception:
                    cancel_native.set()
                    raise
                finally:
                    step('weights_chown',commands['weights_chown'])
                step('weights_verify',commands['weights_verify'])
        parallel(weights,native,cancel_native.set)
        step('proxy_build',['node','proxy/build.ts','--platform','linux/amd64'])
    finally:
        ended=datetime.now(timezone.utc)
        timings.update(worker_build_seconds=time.monotonic()-began,total_setup_seconds=(ended-datetime.fromisoformat(timings['started_at'])).total_seconds(),ended_at=ended.isoformat())
        body=json.dumps(timings,indent=2)+'\n'
        timing_path.write_text(body)
        mirror=context/'results/session4' if not rehearsal else context/'session4'
        mirror.mkdir(parents=True,exist_ok=True);(mirror/'setup_timings.json').write_text(body)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--atlas',type=Path,required=True)
    p.add_argument('--rehearsal',action='store_true')
    p.add_argument('--record-step');p.add_argument('--seconds',type=float);a=p.parse_args()
    if a.record_step:
        context=a.root/'results/rehearsal' if a.rehearsal else a.root
        path=context/'logs/setup_timings.json';path.parent.mkdir(parents=True,exist_ok=True)
        d=json.loads(path.read_text()) if path.exists() else dict(started_at=(datetime.now(timezone.utc)-timedelta(seconds=a.seconds)).isoformat(),rehearsal=a.rehearsal,steps={})
        d['steps'][a.record_step]=dict(seconds=a.seconds,exit_code=0)
        path.write_text(json.dumps(d,indent=2)+'\n')
    else:
        setup(a.root,a.atlas,a.rehearsal)
