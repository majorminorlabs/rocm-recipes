#!/usr/bin/env python3
"""Mac-local input gates shared with the session-4 controller; no dispatch."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime,timezone
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from session4_006 import lifecycle,verify_bundle,prepare,PIN,BUNDLE
from session4_flow_006 import validate_server
from session4_recover_006 import restore,verify_checkpoint


def check(root,atlas,now=None):
    now=now or datetime.now(timezone.utc)
    try:lifecycle(now)  # Same cap/deadline/nonfuture/unexpired gate as the controller.
    except ValueError as error:
        if str(error).startswith('Outside session-4 lifecycle'):
            created=datetime.fromisoformat(os.environ['CREATED_AT'].replace('Z','+00:00'))
            raise ValueError('CREATED_AT is in the future' if now<created else 'HARD_DEADLINE has passed; supply the next session lifecycle') from error
        raise
    state=json.loads((root/'STATE.json').read_text())
    for i in range(3,9):
        if state['steps'][f'P0.{i}']['status']!='DONE':raise ValueError(f'Review prerequisite P0.{i} is not DONE')
    verify_bundle(root/BUNDLE)
    choice=json.loads((root/BUNDLE/'engine_choice.json').read_text())
    if choice['engine']!='vllm' or choice['atlas_commit']!=PIN:raise ValueError('Session-3 engine choice differs')
    server=json.loads((root/'results/droplet_logs/current_server.json').read_text());validate_server(server)
    if os.environ.get('VLLM_IMAGE',server['image'])!=server['image']:raise ValueError('Configured vLLM image differs from the frozen served image')
    if subprocess.check_output(['git','-C',str(atlas),'rev-parse','HEAD'],text=True).strip()!=PIN:raise ValueError('Wrong ATLAS pin')
    if subprocess.check_output(['git','-C',str(atlas),'status','--porcelain','--untracked-files=no'],text=True).strip():raise ValueError('Tracked ATLAS source changed')
    scope=root/'results/session4';checkpoint=verify_checkpoint(root)
    if 'resume_c16.json' in checkpoint['files'] and (root/'results/atlas/scored/live/c16/runs.json').read_bytes()!=(scope/'resume_c16.json').read_bytes():
        raise ValueError('Current c16 export differs from its checkpointed completed report')
    registry=json.loads((scope/'pending_native.json').read_text())
    if any(r.get('status')!='complete' for r in registry['runs']):raise ValueError('Native grading must complete before c8')
    progress=json.loads((scope/'progress.json').read_text())
    if progress['remaining']!=['c8','c4','c1'] or [r['level'] for r in progress['completed']]!=['c16'] or progress.get('active') is not None:
        raise ValueError('Progress must have completed c16, inactive, remaining c8 -> c4 -> c1')
    previous=progress['completed'][0]
    if not previous.get('execution_complete') or previous.get('attempts')!=32 or not isinstance(previous.get('observed_wall_s'),(int,float)) or not math.isfinite(previous['observed_wall_s']) or previous['observed_wall_s']<=0:
        raise ValueError('Completed c16 execution/budget inputs are missing')
    with tempfile.TemporaryDirectory(prefix='rocm006-preflight-') as tmp:
        staged=Path(tmp);work=staged/'atlas';work.mkdir()
        (work/'campaigns').symlink_to(atlas/'campaigns',target_is_directory=True)
        (staged/'inputs').mkdir();(staged/BUNDLE).symlink_to(root/BUNDLE,target_is_directory=True)
        # Use the real restore and immutable manifest preparation in scratch space.
        (staged/'results').mkdir();(staged/'results/session4').symlink_to(scope,target_is_directory=True)
        # Restore's report mirror must stay in scratch, never the caller's results.
        with redirect_stdout(io.StringIO()):restore(staged,work)
        plan=prepare(staged,work)
        report=json.loads((work/'data/rocm-recipes-006/live/c16/runs.json').read_text())
        if not report['execution_complete'] or report.get('pending_native_grades') or any(r.get('native_grade_pending') for r in report['rows']):
            raise ValueError('Restored c16 report still blocks on native grading')
        if len(report['rows'])!=32:raise ValueError('Restored c16 export is incomplete')
        counts={level:plan['levels'][level]['new_runs'] for level in ('c16','c8','c4','c1')}
        if counts!={'c16':30,'c8':30,'c4':30,'c1':7}:raise ValueError('Remaining manifest/budget counts differ from Amendment A')
        manifests=[work/plan['levels'][level]['manifest'] for level in progress['remaining']]
        for path in manifests:
            if not path.is_file():raise ValueError('Manifest reference does not resolve: '+str(path))
        image_map=scope/'atlas/data/rocm-recipes-006-native-session4/image-map.json'
        result=subprocess.run(['node',str(root/'scripts/preflight_refs_006.ts'),str(atlas),str(scope/'atlas/data'),str(image_map),*map(str,manifests)],cwd=atlas,capture_output=True,text=True)
        if result.returncode:raise ValueError('Manifest/image-map references: '+result.stderr.strip())
    return 'PREFLIGHT OK'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--atlas',type=Path,required=True);a=p.parse_args()
    try:print(check(a.root.resolve(),a.atlas.resolve()))
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as error:p.exit(1,'PREFLIGHT FAIL: '+str(error)+'\n')
