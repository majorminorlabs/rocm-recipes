#!/usr/bin/env python3
"""Local CPU dry run of Amendment A; no SSH, Docker, native grading, or cloud.

Uses real frozen manifest loading/SQLite registration, the fake streaming vLLM,
pinned proxy SSE parser, sampler, queue controller, and live/matched summarizer.
Fixture verdicts do not represent hidden-test results or a native-host rehearsal.
"""
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request
from unittest.mock import patch

import fake_engine_006
import gpu_sampler
import session4_006 as s4
import session4_flow_006 as flow
from summarize_006 import summarize, write_csv, write_matched

ROOT=Path(__file__).resolve().parents[1]


def check(atlas, output):
    if os.environ.get('REHEARSAL')!='1':
        raise ValueError('REHEARSAL=1 required')
    if not output.resolve().is_relative_to((ROOT/'results/rehearsal').resolve()) or output.exists():
        raise ValueError('Use a fresh directory inside results/rehearsal')
    output.mkdir(parents=True)
    root=output/'study';work=root/'atlas';work.mkdir(parents=True)
    (work/'campaigns').symlink_to(atlas/'campaigns',target_is_directory=True)
    (root/'inputs').mkdir();shutil.copytree(ROOT/s4.BUNDLE,root/s4.BUNDLE)
    shutil.copyfile(ROOT/'STATE.json',root/'STATE.json')
    plan=s4.prepare(root,work,True)
    context=root/'results/rehearsal';logs=context/'logs';logs.mkdir(parents=True)
    (logs/'current_server.json').write_text(json.dumps(fake_engine_006.server_metadata('vllm')))
    history=json.loads(gzip.decompress((root/s4.BUNDLE/'history.json.gz').read_bytes()))
    reports=[];sample_paths=[];order=[];assertions=[]
    # Fail if port 8000 is occupied; never touch someone else's process.
    server=fake_engine_006.Server(('127.0.0.1',8000),'vllm')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    db=work/'data/rocm-recipes-006-rehearsal/atlas.db'

    def dispatch(level):
        order.append(level);m=json.loads((work/plan['levels'][level]['manifest']).read_text())
        before=gpu_sampler.sample('vllm');before.update(level=level,boundary='before')
        rows=[]
        for spec in m['runs']:
            started=datetime.now(timezone.utc).isoformat();start=time.monotonic();streams=[]
            body=dict(model=fake_engine_006.MODEL,stream=True,messages=[dict(role='user',content='CPU rehearsal read-only tool check')],tools=[dict(type='function',function=dict(name='bash',parameters=dict(type='object')))])
            for turn in range(2):
                request=urllib.request.Request('http://localhost:8000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=5) as r:raw=r.read().decode()
                streams.append(raw)
                if turn==0:
                    events=[json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
                    call=next(c for e in events for c in e.get('choices',[]) if c['delta'].get('tool_calls'))['delta']['tool_calls'][0]
                    body['messages'] += [dict(role='assistant',tool_calls=[call]),dict(role='tool',tool_call_id=call['id'],content='/workspace')]
            parsed=output/(level+'-'+spec['task']+'.sse');parsed.write_text(streams[-1])
            # Real pinned proxy parser checks structured streaming + usage.
            script=output/'parse.mts'
            script.write_text('import{readFileSync}from"node:fs";import{parseEvidence}from'+json.dumps(str(atlas/'proxy/gateway.ts'))+';const e=parseEvidence("/v1/chat/completions",readFileSync(process.argv[2],"utf8"),true);if(e.usage?.cached!==2048||e.usage?.output!==16)throw Error("fake usage parse");')
            subprocess.run(['node',str(script),str(parsed)],cwd=atlas,check=True,capture_output=True)
            rows.append(dict(run_id=f"{spec['task']}__{spec['config']}__a{spec['attempt']}",task=spec['task'],config=spec['config'],model=fake_engine_006.MODEL,
                level=level,study_session=4,attempt=spec['attempt'],retry_of=spec.get('retryOf'),started_at=started,ended_at=datetime.now(timezone.utc).isoformat(),wall_s=time.monotonic()-start,
                category='fixture',end_reason='completed',fixture=True,scored=False,rehearsal=True,solved_by_tests=False,tests_passed=None,tamper=None,
                tokens_in=8192,tokens_out=32,tokens_cached=2048 if len(rows)==0 and level=='c16' else 4096,
                missing_status=True,grading_pending=True,flags=['local dry-run; native tests not executed'],model_latency_s=None,ttft_s=None))
        after=gpu_sampler.sample('vllm');after.update(level=level,boundary='after')
        sample=context/f'raw/{level}/samples.jsonl';sample.parent.mkdir(parents=True)
        sample.write_text('\n'.join(json.dumps(s) for s in (before,after))+'\n');sample_paths.append(sample)
        if level=='c1':
            for entry in history['entries']:
                r=entry['row'];g=entry['grade'];infra=r['end_reason']=='infra'
                rows.append(dict(run_id=r['run_id'],task=r['task_id'],config=r['config_id'],model=r['model'],level=level,study_session=3,
                    started_at=r['started_at'],ended_at=r['ended_at'],wall_s=r['wall_s'],category='infra_error' if infra else g['category'],end_reason=r['end_reason'],
                    fixture=True,scored=False,rehearsal=True,solved_by_tests=False,tests_passed=None if infra else g['tests']['testsPassed'],tamper=None if infra else g['protection']['tamper'],
                    tokens_in=r['tokens_in'],tokens_out=r['tokens_out'],tokens_cached=r['tokens_cached'],grading_pending=False,missing_status=False))
        # Register actual derived manifests in the restored SQLite DB via pinned Store.
        script=output/'register.mts'
        script.write_text('import{Store}from'+json.dumps(str(atlas/'runner/store.ts'))+';import{loadManifest}from'+json.dumps(str(atlas/'runner/manifest.ts'))+';const s=new Store(process.argv[3]);try{s.register(await loadManifest(process.argv[2]));}finally{s.close();}')
        subprocess.run(['node',str(script),str(work/plan['levels'][level]['manifest']),str(db)],cwd=atlas,check=True,capture_output=True)
        path=context/f'atlas/main/live/{level}/runs.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(complete=False,execution_complete=False,local_dry_run=True,atlas_commit=s4.PIN,rehearsal=True,scored=False,matched_tasks=plan['matched_tasks'],rows=rows),indent=2)+'\n');reports.append(path)
        counts=context/f'grading/counts/{level}.json';counts.parent.mkdir(parents=True,exist_ok=True)
        counts.write_text(json.dumps(dict(level=level,pending_mac_grades=len(m['runs']),local_fixture=True))+'\n')
        levels,normalized=summarize(reports,sample_paths,allow_fixtures=True,allow_pending=True)
        live=context/'live';live.mkdir(exist_ok=True);write_csv(live/'summary.csv',levels);write_csv(live/'runs.csv',normalized);write_matched(live,levels,normalized)
        assertions.append(dict(level=level,new_runs=len(m['runs']),null_gpu=before['peak_vram_mb'] is None,ttft_present=after['engine_ttft_histogram'] is not None))

    now=datetime.now(timezone.utc)
    try:
        with patch.dict(os.environ,SESSION4='1',CREATED_AT=now.isoformat(),HARD_DEADLINE=(now+timedelta(hours=10.5)).isoformat(),SESSION_CAP_HOURS='10'):
            flow.run(root,dispatch=dispatch)
    finally:
        server.shutdown();server.server_close();thread.join()
    if order!=list(s4.ORDER):raise AssertionError(order)
    result=dict(rehearsal=True,scored=False,local_dry_run=True,order=order,checks=assertions,
                pinned_atlas=s4.PIN,native_grading_exercised=False,root_ssh_exercised=False,docker_exercised=False,
                matched_tasks=plan['matched_tasks'],pending_counts={l:plan['levels'][l]['new_runs'] for l in order})
    (output/'check.json').write_text(json.dumps(result,indent=2)+'\n')
    shutil.copytree(work/plan['levels']['c1']['manifest'].rsplit('/',1)[0],output/'manifests')
    (work/'campaigns').unlink()
    shutil.rmtree(root/'inputs')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--atlas',type=Path,default=Path('../atlas'))
    p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();check(a.atlas,a.output_dir)
