#!/usr/bin/env python3
"""Optional Phase 3b orchestration on the existing droplet. Never launches main ATLAS work."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from rehearsal_006 import enabled, results, context, TOKENIZER_REVISION


def remaining():
    if enabled():
        return 3600, 3600  # CPU rehearsal has no GPU lifecycle budget.
    now = datetime.now(timezone.utc)
    created = datetime.fromisoformat(os.environ['CREATED_AT'].replace('Z', '+00:00'))
    deadline = datetime.fromisoformat(os.environ['HARD_DEADLINE'].replace('Z', '+00:00'))
    if created.tzinfo is None or deadline.tzinfo is None:
        raise ValueError('Lifecycle timestamps need offsets')
    elapsed = (now - created).total_seconds()
    return (deadline - now).total_seconds(), (float(os.environ.get('SESSION_CAP_HOURS', '9')) - .5) * 3600 - elapsed


def drop_reason(root):
    if os.environ.get('KX_SKIP') == '1':
        return 'dippo requested that section 5b be dropped (KX_SKIP=1)'
    if enabled():
        for level in ('c1','c4','c8','c16'):
            report = json.loads((results(root)/f'atlas/main/live/{level}/runs.json').read_text())
            if not report.get('rehearsal') or not report.get('execution_complete') or len(report['rows']) != 2:
                return 'incomplete CPU rehearsal: '+level
        return None
    state = json.loads((root / 'STATE.json').read_text())
    for step in ('P0.8', 'P0.9', 'P3'):
        if state['steps'][step]['status'] != 'DONE':
            return f'{step} is not DONE'
    projection = json.loads((context(root) / 'notes/budget_check.json').read_text())['projected_without_5b_gpu_hours']
    if projection > 9.5:
        return f'c1 projection without 5b is {projection:.6f} GPU-hours, above 9.5'
    deadline_s, cap_s = remaining()
    if deadline_s < 3600:
        return 'less than 60 minutes remain before HARD_DEADLINE'
    if cap_s <= 0:
        return 'session wrap-up threshold reached'
    with (results(root) / 'live/summary.csv').open() as f:
        levels = {r['level']: r for r in csv.DictReader(f)}
    for level, count in [('c1', 30), ('c4', 30), ('c8', 30), ('c16', 60)]:
        if int(levels[level]['runs']) != count:
            return 'main scored runs incomplete: ' + level
    if 'c32' in levels and int(levels['c32']['runs']) != 30:
        return 'optional c32 was started but is incomplete'
    return None


def friction(root, reason):
    with (context(root) / 'notes/friction.md').open('a') as out:
        out.write(f'\n{datetime.now(timezone.utc).isoformat()} — Section 5b skipped/stopped: {reason}. Main study unaffected.\n')


def report(root, runs, reason=None):
    lines = ['# Prefix scheduling (section 5b)', '', 'Design credit: @thewidechaos.', 'CPU rehearsal (unscored).' if enabled() else 'Production workload.', '', 'Per-group TTFT percentiles include successful requests only; failed counts include all other statuses.', '']
    if reason:
        lines += [f'Skipped/stopped: {reason}.', '']
    for run in runs:
        lines += [f'## {run["run_id"]}', '', f'Overall metric delta: {run["overall_metric_delta"]}; metric: {run["cache_metric_name"]} ({run["cache_metric_type"]}).',
                  f'Output tok/s: {run["output_tok_per_s"]}; requests/s: {run["request_throughput"]}; usage hit fraction: {run["overall_usage_hit_rate"]}.', '',
                  '| Group | Requests | Failed | Cached / prompt | TTFT p50 s | TTFT p95 s |', '|---|---:|---:|---:|---:|---:|']
        for g, data in run['groups'].items():
            lines.append(f'| {g} | {data["requests"]} | {data["failed"]} | {data["hit_rate"]} | {data["ttft_p50_s"]} | {data["ttft_p95_s"]} |')
        lines.append('')
    for start in range(0,len(runs)-1,2):
        fcfs,lpm=runs[start:start+2]
        lines += [f'## FCFS vs LPM at c{fcfs["concurrency"]}', '', '| Group | FCFS requests | FCFS failed | FCFS hit rate | FCFS p50 s | FCFS p95 s | LPM requests | LPM failed | LPM hit rate | LPM p50 s | LPM p95 s |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for g in fcfs['groups']:
            a,b=fcfs['groups'][g],lpm['groups'][g]
            lines.append(f'| {g} | {a["requests"]} | {a["failed"]} | {a["hit_rate"]} | {a["ttft_p50_s"]} | {a["ttft_p95_s"]} | {b["requests"]} | {b["failed"]} | {b["hit_rate"]} | {b["ttft_p50_s"]} | {b["ttft_p95_s"]} |')
        lines.append('')
    if len(runs) >= 2:
        fcfs, lpm = runs[:2]
        waiting = [g for g in fcfs['groups'] if fcfs['groups'][g]['ttft_p95_s'] is not None and lpm['groups'][g]['ttft_p95_s'] is not None and lpm['groups'][g]['ttft_p95_s'] > fcfs['groups'][g]['ttft_p95_s']]
        verb = 'helped' if lpm['request_throughput'] > fcfs['request_throughput'] else 'did not help'
        lines.append(f'At c{fcfs["concurrency"]}, LPM {verb} overall request throughput ({fcfs["request_throughput"]:.6f} to {lpm["request_throughput"]:.6f} requests/s), and groups {", ".join(waiting) if waiting else "none"} had longer p95 waits.')
    (context(root) / 'notes/kx_report.md').write_text('\n'.join(lines) + '\n')
    state_path=context(root)/'STATE.json'
    state=json.loads(state_path.read_text())
    step=state['steps'].setdefault('P3b', {})
    step.update(status='DONE' if len(runs)>=2 else 'BLOCKED', note=reason or 'Section 5b complete; notes/kx_report.md', attempts=step.get('attempts',0)+1)
    state_path.write_text(json.dumps(state,indent=2)+'\n')


def run(root):
    root = root.resolve(); (context(root) / 'notes').mkdir(exist_ok=True)
    runs = []
    stop = ['bash',str(root/'scripts/atlas_remote.sh'),'--remote',str(root),'_stop']
    def command(args, timeout=None):
        deadline_s, cap_s = remaining()
        limit = min(deadline_s, cap_s, timeout if timeout is not None else cap_s)
        if limit <= 0:
            raise ValueError('session wrap-up threshold reached')
        subprocess.run(args, cwd=root, check=True, timeout=limit)
    def serve(policy):
        command(['bash', str(root / 'scripts/atlas_remote.sh'), '--remote', str(root), '_kx-serve', policy])
    def client(name, prompts, concurrency):
        target = results(root) / 'raw/Kx' / name
        command(['python3', str(root / 'scripts/prefix_sched.py'), '--prompts', str(prompts), '--output-dir', str(target), '--concurrency', str(concurrency), '--run-id', name], timeout=180 if name == 'Kx-0' else None)
        return json.loads((target / 'summary.json').read_text())
    try:
        reason = drop_reason(root)
        if reason:
            friction(root, reason); report(root, [], reason); return
        with (results(root) / 'live/summary.csv').open() as f:
            levels = {r['level']: r for r in csv.DictReader(f)}
        highest = 4 if enabled() else 32 if 'c32' in levels else 16
        current = json.loads((context(root) / 'logs/current_server.json').read_text())
        image = os.environ['SGLANG_IMAGE']; scratch = os.environ.get('SCRATCH_DIR', '/mnt/scratch')
        (results(root) / 'raw/Kx').mkdir(parents=True, exist_ok=True)
        prompts = results(root) / 'raw/Kx/prompts'
        hf = results(root)/'hf' if enabled() else Path(scratch)/'hf'
        if enabled(): hf.mkdir(parents=True, exist_ok=True)
        user = f'{os.getuid()}:{os.getgid()}'
        if enabled():
            command(['docker','run','--rm','--user',user,'--entrypoint','python3','-e','HF_HOME=/hf','-e','HF_HUB_CACHE=/hf/hub','-e','HF_HUB_OFFLINE=0','-e','TRANSFORMERS_OFFLINE=0','-e','HOME=/tmp',
                     '-v',f'{hf}:/hf',image,'-c',
                     'from transformers import AutoTokenizer; AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B",revision="'+TOKENIZER_REVISION+'")'])
        args = ['docker', 'run', '--rm', '--user', user, '--entrypoint', 'python3', '-e', 'HF_HUB_OFFLINE=1', '-e', 'HF_HOME=/hf', '-e', 'HF_HUB_CACHE=/hf/hub', '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'HOME=/tmp',
                '-v', f'{root}/scripts:/scripts:ro', '-v', f'{root}/atlas/tasks:/atlas/tasks:ro',
                '-v', f'{results(root)}:/results', '-v', f'{hf}:/hf:ro',
                image, '/scripts/make_wmp_prompts.py', '--atlas', '/atlas', '--output', '/results/raw/Kx/prompts',
                '--revision', current.get('model_revision') or 'main']
        if enabled(): args += ['--rehearsal']
        if (results(root) / 'live/c1_proxy_usage.jsonl').exists():
            args += ['--proxy-logs', '/results/live/c1_proxy_usage.jsonl']
        # Missing provenance is non-fatal: resolve the cached main ref offline.
        # Prompt building is separate from inference and never changes a frozen file.
        command(args)
        serve('fcfs')
        check = client('Kx-0', prompts / 'kx-0.jsonl', 1)
        (context(root) / 'notes/kx_metrics.md').write_text('# Kx-0 metric check\n\n' + json.dumps({k: v for k, v in check.items() if k.startswith('cache_metric') or k in ('overall_metric_delta', 'metric_interpretation')}, indent=2) + '\n\nThe expected metric is a gauge in current SGLang; its delta is a rate change, not a cumulative hit fraction. Per-group and overall usage hit fractions are reported separately when cached usage is returned.\n')
        if not (check['ok'] == 8 and all(g['requests'] == 2 for g in check['groups'].values())
                and check['cache_metric_name'] and check['cache_metric_changed']):
            raise ValueError('Kx-0: missing/unchanged hit-rate metric, failed requests or missing group tags')
        serve('lpm')  # Readiness must pass before any measurement is admitted.
        command(stop)
        for concurrency, count in ([(4,20)] if enabled() else [(highest, 256), (8, 128)]):
            reason = drop_reason(root)
            if reason:
                friction(root, reason); report(root, runs, reason); return
            # Optional c8 is admitted only with room for its entire pair before wrap-up.
            if concurrency == 8 and remaining()[1] < 8 * 60:
                reason = 'insufficient session time for optional c8 FCFS/LPM pair'
                friction(root, reason); report(root, runs, reason); return
            for policy in ('fcfs', 'lpm'):
                reason = drop_reason(root)
                if reason:
                    friction(root, reason); report(root, runs, reason); return
                serve(policy)
                result = client(f'Kx-{policy.upper()}-c{concurrency}', prompts / f'wmp-{count}.jsonl', concurrency)
                runs.append(result)
                command(stop)
        report(root, runs)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        friction(root, str(error)); report(root, runs, str(error))
    finally:
        # Stop only the study engine. No Docker prune, lifecycle or cloud commands.
        if runs or (results(root) / 'raw/Kx/Kx-0').exists():
            subprocess.run(stop, cwd=root, check=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, required=True)
    run(p.parse_args().root)
