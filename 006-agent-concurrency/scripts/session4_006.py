#!/usr/bin/env python3
"""Amendment A: immutable resume bundle, derived manifests, and between-level budget.

No cloud access. Never writes the retained session-3 SQLite database or grades.
"""
import argparse
import copy
import hashlib
import gzip
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ORDER = ('c16', 'c8', 'c4', 'c1')
PIN = '279889b8f42c607344781766503602a8c462f5df'
CONFIG = 'qwen38-27b-mi300x'
BUNDLE = 'inputs/session4'
CAMPAIGN = 'data/rocm-recipes-006-session4'
POST_GRADE = {'tests_passed', 'tamper', 'claim', 'claim_source', 'category', 'flags'}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, indent=2) + '\n'
    if path.exists() and path.read_text() != body:
        raise ValueError('Refusing to replace immutable session-4 input: ' + str(path))
    path.write_text(body)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen(atlas, level):
    return json.loads((atlas / f'campaigns/rocm-recipes-006/manifests/{level}.json').read_text())


def bundle(root, atlas):
    """Checkpoint a COPY, bind the three existing native verdicts, keep all old rows."""
    destination = root / BUNDLE
    if destination.exists():
        verify_bundle(destination)
        return
    source = root / 'results/atlas/data/rocm-recipes-006/atlas.db'
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        for p in source.parent.glob('atlas.db*'):
            shutil.copyfile(p, Path(tmp) / p.name)
        db = sqlite3.connect(Path(tmp) / source.name)
        db.row_factory = sqlite3.Row
        if db.execute('SELECT count(*) FROM sessions WHERE ended_at IS NULL').fetchone()[0]:
            raise ValueError('Session-3 DB still has a live owner; inspect before restoring')
        out = sqlite3.connect(destination / 'atlas.db')
        db.backup(out); out.close()
        matched = [r['task'] for r in frozen(atlas, 'c1')['runs'][:10]]
        history = []
        for task in matched:
            row = dict(db.execute('SELECT * FROM runs WHERE run_id=?', (f'{task}__{CONFIG}__a1',)).fetchone())
            if row['state'] != 'finished':
                continue
            entry = dict(row=row, grade=None)
            if row['end_reason'] != 'infra':
                meta = dict(db.execute('SELECT * FROM grades WHERE run_id=?', (row['run_id'],)).fetchone())
                relative = meta['path'].split('/atlas/data/', 1)[1]
                path = root / 'results/atlas/data' / relative
                grade = json.loads(path.read_text())
                if meta['status'] != 'complete' or grade['status'] != 'complete' or grade['fingerprint'] != meta['fingerprint'] or grade['runId'] != row['run_id']:
                    raise ValueError('Unbound historical native grade: ' + row['run_id'])
                if any(grade['executionRow'].get(k) != v for k, v in row.items() if k not in POST_GRADE):
                    raise ValueError('Historical execution differs from cached grade')
                entry.update(grade=grade, grade_metadata=meta, grade_file_sha256=sha(path), grade_source=str(path.relative_to(root)))
            history.append(entry)
        db.close()
    if {e['row']['task_id'] for e in history if e['grade']} != {'c18', 'c09', 'c28'}:
        raise ValueError('Expected the three session-3 c1 native grades')
    choice = json.loads((root / 'notes/engine_choice.json').read_text())
    if choice['engine'] != 'vllm' or choice['atlas_commit'] != PIN:
        raise ValueError('Session-3 choice does not match Amendment A')
    (destination / 'history.json.gz').write_bytes(gzip.compress((json.dumps(dict(atlas_commit=PIN, matched_tasks=matched, entries=history))+'\n').encode(),mtime=0))
    shutil.copyfile(root / 'notes/engine_choice.json', destination / 'engine_choice.json')
    save(destination / 'checksums.json', {p.name: sha(p) for p in sorted(destination.iterdir())})


def verify_bundle(path):
    for name, expected in json.loads((path / 'checksums.json').read_text()).items():
        if Path(name).name != name or sha(path / name) != expected:
            raise ValueError('Resume input changed: ' + name)


def prepare(root, atlas, rehearsal=False):
    path = root / BUNDLE
    verify_bundle(path)
    history = json.loads(gzip.decompress((path / 'history.json.gz').read_bytes()))
    matched = history['matched_tasks']
    previous = {e['row']['task_id']: e['row'] for e in history['entries']}
    out = atlas / CAMPAIGN
    if rehearsal:
        out = atlas / 'data/rocm-recipes-006-rehearsal-session4'
    out.mkdir(parents=True, exist_ok=True)
    target_db = atlas / ('data/rocm-recipes-006-rehearsal/atlas.db' if rehearsal else 'data/rocm-recipes-006/atlas.db')
    if not target_db.exists():
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path / 'atlas.db', target_db)
    plan = dict(amendment='A', session=4, atlas_commit=PIN, rehearsal=rehearsal,
                matched_tasks=matched, order=list(ORDER), levels={}, history=str(path / 'history.json.gz'))
    for level in ORDER:
        original = frozen(atlas, level)
        m = copy.deepcopy(original)
        selected = []; seen = set()
        for row in original['runs']:
            if row['task'] in seen:
                continue
            seen.add(row['task'])
            if level == 'c1':
                if row['task'] not in matched:
                    continue
                old = previous.get(row['task'])
                if old and old['end_reason'] != 'infra':
                    continue
                row = dict(row, attempt=6)
                if old:
                    row['retryOf'] = old['run_id']
            selected.append(row)
        # Rehearsal retains c1's seven-item resume semantics; other levels are short.
        if rehearsal and level != 'c1':
            selected = selected[:2]
            selected = [dict(r, attempt=400+int(level[1:])) for r in selected]
        m.update(id=f'rocm006-{"rehearsal-" if rehearsal else ""}session4-{level}', runs=selected)
        m['study'].update(repetitions=1, optional=False, dryRun=rehearsal)
        save(out / f'{level}.json', m)
        plan['levels'][level] = dict(new_runs=len(selected), total_tasks=10 if level == 'c1' else len(selected),
                                     manifest=str((out / f'{level}.json').relative_to(atlas)))
    save(out / 'session4.json', plan)
    return plan


def projection(elapsed_h, observed_s, runs, concurrency, remaining, counts, buffer_h=1.0):
    if observed_s <= 0 or runs <= 0:
        raise ValueError('Cannot project without a completed level and positive observed pace')
    # Measured queue wall time, normalized by its actual count and concurrency.
    task_s = observed_s * concurrency / runs
    def total(levels):
        return elapsed_h + buffer_h + sum(task_s * counts[l] / int(l[1:]) / 3600 for l in levels)
    kept = list(remaining); dropped = []; trials = [dict(remaining=list(kept), projected_hours=total(kept))]
    for level in ('c1', 'c4'):
        if total(kept) > 10.5 and level in kept:
            kept.remove(level); dropped.append(level)
            trials.append(dict(remaining=list(kept), projected_hours=total(kept)))
    wrap = total(kept) > 10.5
    return dict(elapsed_hours=elapsed_h, observed_level_wall_s=observed_s, observed_runs=runs,
                observed_concurrency=concurrency, normalized_task_s=task_s, buffer_hours=buffer_h,
                trials=trials, dropped=dropped, remaining=[] if wrap else kept,
                deferred_on_wrap=kept if wrap else [], wrap=wrap,
                reason=('Remaining c16/c8 cannot fit after dropping c1 then c4; wrap up' if wrap and kept else 'Wrap up: no remaining level fits the session envelope' if wrap else 'Reprojected remaining levels fit the session envelope'), projected_hours=total(kept), threshold_hours=10.5)


def lifecycle(now=None):
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(os.environ['CREATED_AT'].replace('Z', '+00:00'))
    deadline = datetime.fromisoformat(os.environ['HARD_DEADLINE'].replace('Z', '+00:00'))
    if created.tzinfo is None or deadline.tzinfo is None or float(os.environ['SESSION_CAP_HOURS']) != 10 or abs((deadline-created).total_seconds()-10.5*3600) > 1:
        raise ValueError('Amendment A requires cap=10 and deadline=CREATED_AT+10.5h')
    elapsed = (now-created).total_seconds()/3600
    if elapsed < 0 or now >= deadline:
        raise ValueError('Outside session-4 lifecycle; wrap up')
    return elapsed


def budget(root, plan, completed, observed_s, remaining, now=None):
    now = now or datetime.now(timezone.utc)
    elapsed = lifecycle(now)
    counts = {l: plan['levels'][l]['new_runs'] for l in ORDER}
    decision = projection(elapsed, observed_s, counts[completed], int(completed[1:]), remaining, counts)
    if plan['rehearsal']:
        decision.update(remaining=list(remaining), dropped=[], deferred_on_wrap=[], wrap=False, rehearsal_budget_bypassed=True)
    context = root / 'results/rehearsal' if plan['rehearsal'] else root
    notes = context / 'notes'; notes.mkdir(parents=True, exist_ok=True)
    record = dict(at=now.isoformat(), completed=completed, **decision)
    with (notes / 'budget_check.jsonl').open('a') as f:
        f.write(json.dumps(record)+'\n')
    with (notes / 'budget_check.md').open('a') as f:
        f.write('\n## Session 4 after '+completed+' ('+now.isoformat()+')\n\n')
        f.write('Projection = elapsed lifecycle + 1h wrap-up buffer + observed queue seconds × observed concurrency / observed new runs × remaining new runs / remaining concurrency. Historical c1 work is excluded from remaining spend.\n\n```json\n'+json.dumps(record, indent=2)+'\n```\n')
    mirror = (root/'results/rehearsal/session4') if plan['rehearsal'] else root/'results/session4'
    mirror.mkdir(parents=True,exist_ok=True)
    for name in ('budget_check.md','budget_check.jsonl'):
        shutil.copyfile(notes/name,mirror/name)
    return decision


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['bundle','prepare','verify'])
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--atlas', type=Path, required=True)
    p.add_argument('--rehearsal', action='store_true')
    a = p.parse_args()
    if a.action == 'verify':
        verify_bundle(a.root / BUNDLE)
    elif a.action == 'bundle':
        bundle(a.root, a.atlas)
    else:
        print(json.dumps(prepare(a.root, a.atlas, a.rehearsal), indent=2))
