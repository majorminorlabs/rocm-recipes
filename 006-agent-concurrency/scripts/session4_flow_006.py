#!/usr/bin/env python3
"""Session 4's uninterrupted descending queues; guard only BETWEEN levels."""
import argparse
from datetime import datetime, timezone
import json
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import time
from session4_006 import ORDER, budget, lifecycle, verify_bundle, BUNDLE
from session4_setup_006 import MODEL, REVISION


# Compare only frozen settings, never the complete per-session metadata object.
FROZEN_SERVER = {
    'engine': 'vllm',
    'hf_repo': MODEL,
    'model_revision': REVISION,
    'weights_precision': 'bf16',
    'max_model_len': 131072,
    'server_args.dtype': 'bf16',
    'server_args.max_model_len': 131072,
    'server_args.tool_call_parser': 'qwen3_coder',
    'server_args.reasoning_parser': 'qwen3',
    'server_args.enable_auto_tool_choice': True,
    'server_args.enable_prompt_tokens_details': True,
}


def frozen_server_settings(server):
    """Project the real launch/provenance schema onto the frozen settings only."""
    try:
        raw = server.get('server_args')
        args = shlex.split(raw) if isinstance(raw,str) else []
    except (ValueError, TypeError):
        args = []

    def option(flag, boolean=False):
        value = None
        for i, arg in enumerate(args):
            if arg == flag:
                value = True if boolean else args[i+1] if i+1 < len(args) and not args[i+1].startswith('--') else None
            elif arg.startswith(flag+'='):
                value = arg.split('=',1)[1]
                if boolean and value.lower() in ('true','false'):
                    value = value.lower() == 'true'
            elif boolean and arg == '--no-'+flag[2:]:
                value = False
        return value

    def precision(value):
        return 'bf16' if isinstance(value,str) and value.lower() in ('bf16','bfloat16') else value

    def context(value):
        return int(value) if isinstance(value,str) and value.isdecimal() else value

    return {
        'engine': server.get('engine'),
        'hf_repo': server.get('hf_repo'),
        'model_revision': server.get('model_revision'),
        'weights_precision': precision(server.get('weights_precision')),
        'max_model_len': context(server.get('max_model_len')),
        'server_args.dtype': precision(option('--dtype')),
        'server_args.max_model_len': context(option('--max-model-len')),
        'server_args.tool_call_parser': option('--tool-call-parser'),
        'server_args.reasoning_parser': option('--reasoning-parser'),
        'server_args.enable_auto_tool_choice': option('--enable-auto-tool-choice',True),
        'server_args.enable_prompt_tokens_details': option('--enable-prompt-tokens-details',True),
    }


def validate_server(server):
    actual = frozen_server_settings(server)
    if any(actual[field] != expected for field,expected in FROZEN_SERVER.items()):
        details = ['Served engine differs from session-3 choice/frozen settings:']
        for field,expected in FROZEN_SERVER.items():
            observed = actual[field]
            status = 'OK' if observed == expected else 'MISMATCH'
            details.append(f'  {field}: expected={json.dumps(expected)}, actual={json.dumps(observed)} [{status}]')
        raise ValueError('\n'.join(details))
    return actual


def run(root, dispatch=None, clock=time.monotonic):
    lifecycle()
    rehearsal=os.environ.get('REHEARSAL')=='1'
    context=root/'results/rehearsal' if rehearsal else root
    atlas=root/'atlas'
    campaign='data/rocm-recipes-006-rehearsal-session4' if rehearsal else 'data/rocm-recipes-006-session4'
    plan=json.loads((atlas/campaign/'session4.json').read_text())
    verify_bundle(root/BUNDLE)
    choice=json.loads((root/BUNDLE/'engine_choice.json').read_text())
    if choice['engine']!='vllm':
        raise ValueError('Amendment A requires the saved session-3 vLLM choice')
    server=json.loads((context/'logs/current_server.json').read_text())
    validate_server(server)
    pending_path=root/'results/session4/pending_native.json'
    if not rehearsal and pending_path.exists() and any(r.get('status')!='complete' for r in json.loads(pending_path.read_text())['runs']):
        raise ValueError('Pending native grades must finish after check-host and before c8')
    state=json.loads((root/'STATE.json').read_text())
    for i in range(3,9):
        if state['steps'][f'P0.{i}']['status']!='DONE':
            raise ValueError('Review prerequisite is not DONE')
    if dispatch is None:
        def dispatch(level):
            subprocess.run(['bash',str(root/'scripts/atlas_remote.sh'),'--remote',str(root),'_s4-level',level],check=True)
    progress_path=(context/'session4/progress.json') if rehearsal else root/'results/session4/progress.json'
    if progress_path.exists():
        progress=json.loads(progress_path.read_text())
        remaining=list(progress['remaining'])
    else:
        progress=dict(completed=[],remaining=list(ORDER));remaining=list(ORDER)
    def save_progress():
        progress_path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('w',dir=progress_path.parent,delete=False) as f:
            json.dump(progress,f,indent=2);f.write('\n')
        os.replace(f.name,progress_path)

    while remaining:
        level=remaining.pop(0)
        began=clock()
        active=progress.get('active')
        started=active['started_at'] if active and active['level']==level else datetime.now(timezone.utc).isoformat()
        progress['active']=dict(level=level,started_at=started)
        save_progress()
        dispatch(level)  # no budget timeout; unchanged external watchdog is the deadline
        observed=max(clock()-began,(datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds())
        decision=budget(root,plan,level,observed,remaining)
        remaining=list(decision['remaining'])
        progress['completed'].append(dict(level=level,observed_wall_s=observed,decision=decision))
        progress['remaining']=list(remaining)
        progress['active']=None
        save_progress()
        print(json.dumps(dict(completed=level,decision=decision)),flush=True)
    print('Session 4 queues finished or budget guard requested wrap-up. Sync, Mac-grade, wrap up and destroy per PLAN; no idle wait for claims.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    run(p.parse_args().root)
