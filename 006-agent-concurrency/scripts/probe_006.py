#!/usr/bin/env python3
"""Prepare R1's one-task smoke and exactly eight seeded c8 tasks, without dispatch."""
import json
import os
from pathlib import Path

REQUIRED = {'c13', 'c18', 'c45'}


def select(runs):
    selected = {r['task'] for r in runs[:8]}
    if len(selected) != 8 or not REQUIRED <= {r['task'] for r in runs}:
        raise ValueError('Expected eight distinct seed selections and all required tasks')
    for row in runs:
        task = row['task']
        if task in REQUIRED and task not in selected:
            victim = next(r['task'] for r in reversed(runs[:8]) if r['task'] in selected - REQUIRED)
            selected.remove(victim)
            selected.add(task)
    return [r for r in runs if r['task'] in selected]


def prepare(atlas):
    source = atlas / 'campaigns/rocm-recipes-006/manifests/c8.json'
    original = json.loads(source.read_text())
    selected = select(original['runs'])
    smoke = next(r for r in selected if r['task'] in REQUIRED)
    rehearsal = os.environ.get('REHEARSAL') == '1'
    out = atlas / ('data/rocm-recipes-006-rehearsal-probe' if rehearsal else 'data/rocm-recipes-006-probe')
    out.mkdir(parents=True, exist_ok=True)
    for engine in ('vllm', 'sglang'):
        for stage, concurrency, attempt, rows in [('smoke', 1, 71, [smoke]), ('c8', 8, 73, selected)]:
            d = json.loads(json.dumps(original))
            d['id'] = f"rocm006-{'rehearsal-' if rehearsal else ''}probe-{engine}-{stage}"
            d['concurrency'] = concurrency
            d['study'].update(level=f'c{concurrency}', dryRun=True, repetitions=1, optional=False)
            # Separate rehearsal handoffs for both engines (same native task/config).
            unique_attempt = attempt + (100 if rehearsal and engine == 'sglang' else 0)
            d['runs'] = [dict(r, attempt=unique_attempt) for r in rows]
            path = out / f'{engine}-{stage}.json'
            text = json.dumps(d, indent=2) + '\n'
            if path.exists() and path.read_text() != text:
                raise ValueError(f'Refuse changed probe evidence: {path}')
            path.write_text(text)
    return [r['task'] for r in selected]


if __name__ == '__main__':
    import sys
    print(json.dumps(prepare(Path(sys.argv[1]))))
