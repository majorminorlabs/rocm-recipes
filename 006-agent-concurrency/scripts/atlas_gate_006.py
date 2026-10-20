#!/usr/bin/env python3
"""Read-only dispatch checks plus the required budget-check note. No cloud access."""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import os


def gate(root, level):
    state = json.loads((root / 'STATE.json').read_text())
    for step in ('P0.3', 'P0.4', 'P0.5', 'P0.6', 'P0.7', 'P0.8'):
        if state['steps'][step]['status'] != 'DONE':
            raise ValueError(f'{step} is not DONE; no scored dispatch')
    choice = json.loads((root / 'notes/engine_choice.json').read_text())
    server = json.loads((root / 'logs/current_server.json').read_text())
    if server['engine'] != choice['engine'] or server['hf_repo'] != 'Qwen/Qwen3.8-27B':
        raise ValueError('Served engine/model differs from recorded choice')
    if server['max_model_len'] != 131072 or server['weights_precision'] != 'bf16':
        raise ValueError('Unexpected precision/context')
    created = datetime.fromisoformat(os.environ['CREATED_AT'].replace('Z', '+00:00'))
    deadline = datetime.fromisoformat(os.environ['HARD_DEADLINE'].replace('Z', '+00:00'))
    if created.tzinfo is None or deadline.tzinfo is None:
        raise ValueError('Lifecycle timestamps need timezone offsets')
    elapsed = (datetime.now(timezone.utc) - created).total_seconds() / 3600
    if elapsed < 0 or elapsed >= float(os.environ.get('SESSION_CAP_HOURS', '9')) - .5 or datetime.now(timezone.utc) >= deadline:
        raise ValueError('Session wrap-up threshold reached or invalid CREATED_AT')
    if level == 'c1':
        return
    live = root / 'results/live/summary.csv'
    with (live if live.exists() else root / 'results/summary.csv').open() as f:
        rows = {r['level']: r for r in csv.DictReader(f)}
    order = ['c1', 'c4', 'c8', 'c16', 'c32']
    for prior in order[:order.index(level)]:
        r = rows[prior]
        if r['scored'] != 'true' or int(r['runs']) != (60 if prior == 'c16' else 30):
            raise ValueError('Incomplete previous level: ' + prior)
    # At c4 elapsed includes setup + c1; project remaining c4/c8/c16 from c1.
    if level == 'c4':
        projection = elapsed + float(rows['c1']['level_gpu_hours']) * (.25 + .125 + 2 / 16) + .9
        note = f'# Budget check\n\nProjected total: {projection:.6f} GPU-hours (${projection * 1.99:.2f}).\nBasis: elapsed lifecycle + c1 × (1/4 + 1/8 + 2/16) + 0.9h buffer.\n'
        (root / 'notes/budget_check.md').write_text(note)
        (root / 'notes/budget_check.json').write_text(json.dumps({'projected_without_5b_gpu_hours': projection, 'projected_with_5b_gpu_hours': projection + .4}) + '\n')
        if projection > 10:
            raise ValueError('Projection exceeds 10 GPU-hours; stop after c1 and await dippo')
    if level == 'c32':
        c1, c8, c16 = (rows[k] for k in ('c1', 'c8', 'c16'))
        if not (float(c16['successful_tasks_per_hour']) > 1.1 * float(c8['successful_tasks_per_hour'])
                and abs(float(c16['success_rate']) - float(c1['success_rate'])) <= .10):
            raise ValueError('Optional c32 does not meet section 5 criteria')


if __name__ == '__main__':
    try:
        gate(Path(sys.argv[1]), sys.argv[2])
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error))
