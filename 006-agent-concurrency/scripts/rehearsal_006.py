#!/usr/bin/env python3
"""Rehearsal layout/manifests. Uses the pinned native runner, never ATLAS mock mode."""
import json
import os
from pathlib import Path

TOKENIZER_REVISION = '1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0'


def enabled():
    return os.environ.get('REHEARSAL') == '1'


def results(root):
    return root / ('results/rehearsal' if enabled() else 'results')


def context(root):
    return results(root) if enabled() else root


def prepare(atlas):
    out = atlas / 'data/rocm-recipes-006-rehearsal'
    out.mkdir(parents=True, exist_ok=True)
    for concurrency in (1, 4, 8, 16):
        original = json.loads((atlas / f'campaigns/rocm-recipes-006/manifests/c{concurrency}.json').read_text())
        seen = set(); selected = []
        for row in original['runs']:
            if row['task'] not in seen:
                selected.append(dict(row, attempt=300+concurrency)); seen.add(row['task'])
            if len(selected) == 2:
                break
        original.update(id=f'rocm006-rehearsal-c{concurrency}', runs=selected)
        original['study'].update(dryRun=True, repetitions=1, optional=False)
        path = out / f'c{concurrency}.json'
        body = json.dumps(original, indent=2)+'\n'
        if path.exists() and path.read_text() != body:
            raise ValueError('Refuse changed rehearsal manifest: '+str(path))
        path.write_text(body)


def gate(root, level):
    """CPU sequencing gate; production budget/scaling gates remain untouched."""
    if level not in ('c1', 'c4', 'c8', 'c16'):
        raise ValueError('No c32 in CPU rehearsal')
    scope = results(root)
    choice = json.loads((scope/'notes/engine_choice.json').read_text())
    server = json.loads((scope/'logs/current_server.json').read_text())
    if not choice.get('rehearsal') or not server.get('rehearsal') or choice['engine'] != server['engine']:
        raise ValueError('Rehearsal engine identity mismatch')
    for previous in ('c1', 'c4', 'c8', 'c16')[:('c1', 'c4', 'c8', 'c16').index(level)]:
        report = json.loads((scope/f'atlas/main/live/{previous}/runs.json').read_text())
        if not report.get('rehearsal') or not report.get('execution_complete') or len(report['rows']) != 2:
            raise ValueError('Incomplete rehearsal level: '+previous)


if __name__ == '__main__':
    import sys
    if not enabled():
        raise SystemExit('REHEARSAL=1 required')
    prepare(Path(sys.argv[1]))
