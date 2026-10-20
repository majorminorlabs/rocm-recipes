#!/usr/bin/env python3
"""Rebuild 006 CSVs from ATLAS runs.json/runs.csv exports (stdlib only).

JSON includes infra_attempts and campaign metadata and is preferred. Never pass
both representations of the same export. Fixtures require --allow-fixtures and
must be written to a separate directory. Missing measurements stay empty.
"""
import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from ttft_006 import level_ttft

ROOT = Path(__file__).resolve().parents[1]
PIN = '279889b8f42c607344781766503602a8c462f5df'
TOKEN_FIELDS = ('tokens_in', 'tokens_out', 'tokens_cached', 'tokens_uncached_in',
                'tokens_cumulative', 'tokens_counted', 'token_overshoot')
NUMBER_FIELDS = set(TOKEN_FIELDS) | {'attempt', 'wall_s', 'inference_s', 'turns',
    'tool_calls', 'soft_token_limit', 'cap_stop_latency_ms', 'refusal_count', 'cost_usd'}
BOOL_FIELDS = {'native_grade_pending', 'rehearsal', 'grading_pending', 'solved_by_tests', 'missing_status', 'fixture', 'scored', 'tests_passed', 'tamper', 'excluded', 'anecdotal', 'planned_level_dropped'}
LIST_FIELDS = {'flags', 'model_latency_s', 'ttft_s', 'matched_tasks'}


def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamp needs an offset: ' + value)
    return dt.timestamp()


def quantile(values, p):
    if not values or any(v is None for v in values):
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def exact_sum(rows, field):
    values = [r.get(field) for r in rows]
    return sum(values) if all(v is not None for v in values) else None


def mean(rows, field):
    total = exact_sum(rows, field)
    return total / len(rows) if rows and total is not None else None


def failure(row):
    if row.get('native_grade_pending'):
        return 'pending_native_grade'
    if row.get('category') == 'infra_error' or row.get('end_reason') == 'infra':
        return 'infra'
    if row.get('category') == 'solved':
        return ''
    reason = row.get('end_reason')
    category = row.get('category')
    for kind in ('infra', 'timeout', 'turn_cap', 'token_cap', 'context_overflow'):
        if kind in (reason, category):
            return kind
    if 'looped' in (row.get('flags') or []) or category == 'agent_loop':
        return 'agent_loop'
    if category in ('wrong_answer', 'false_success', 'incomplete', 'honest_failure', 'honest_fail', 'no_claim', 'silent_failure', 'tamper'):
        return 'wrong_answer'
    return 'other'  # Keep original category/flags; do not guess a model failure.


def normalize(row):
    row = dict(row)
    for k, v in row.items():
        if v == '':
            row[k] = None
        elif k in BOOL_FIELDS and isinstance(v, str):
            if v.lower() not in ('true', 'false'):
                raise ValueError(f'Invalid boolean {k}: {v}')
            row[k] = v.lower() == 'true'
        elif k in NUMBER_FIELDS and isinstance(v, str):
            row[k] = json.loads(v)
        elif k in LIST_FIELDS and isinstance(v, str):
            row[k] = json.loads(v)
    for k in NUMBER_FIELDS:
        v = row.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                              or not math.isfinite(v) or v < 0):
            raise ValueError(f'Invalid measurement {k}: {v}')
    return row


def load_export(path, allow_pending=False):
    if path.suffix == '.csv':
        with path.open(newline='') as f:
            return {}, [normalize(r) for r in csv.DictReader(f)]
    data = json.loads(path.read_text())
    if data.get('complete') is False and not allow_pending:
        raise ValueError(f'Incomplete export: {path}')
    rows = [normalize(r) for r in data['rows']]
    for raw in data.get('infra_attempts', []):
        r = normalize(raw)
        r.update(category='infra', excluded=True)
        # P0.5's excluded attempts omit level; retry_of is the explicit link.
        targets = [x for x in rows if x.get('retry_of') == r['run_id']]
        if not r.get('level') and len(targets) == 1:
            r['level'] = targets[0]['level']
        for k in ('fixture', 'scored', 'config', 'model'):
            if k not in r and targets:
                r[k] = targets[0].get(k)
        rows.append(r)
    return data, rows


def summarize(paths, sample_paths=(), allow_fixtures=False, allow_pending=False, strict=False):
    rows, seen, timing_gaps, matched_tasks = [], set(), {}, None
    for path in paths:
        data, imported = load_export(path, allow_pending)
        candidate = data.get('matched_tasks') or next((r.get('matched_tasks') for r in imported if r.get('matched_tasks')),None)
        if candidate:
            if matched_tasks and matched_tasks != candidate:
                raise ValueError('Inconsistent matched task sets')
            matched_tasks = candidate
        for row in imported:
            if row.get('grading_pending') and not allow_pending:
                raise ValueError('Final summary blocked by pending Mac grades')
            row.setdefault('fixture', data.get('scored') is False)
            row.setdefault('anecdotal', data.get('anecdotal', False))
            row.setdefault('planned_level_dropped', data.get('planned_level_dropped', False))
            if row.get('fixture') or row.get('scored') is False:
                if not allow_fixtures:
                    raise ValueError('Fixture/unscored export requires --allow-fixtures')
            elif row.get('config') != 'qwen38-27b-mi300x':
                raise ValueError('Unexpected scored config: ' + str(row.get('config')))
            if not re.fullmatch(r'c(1|4|8|16|32)', str(row.get('level'))):
                raise ValueError('Missing/invalid level for ' + row['run_id'])
            key = row['run_id']
            if key in seen:
                raise ValueError('Duplicate run_id (overlapping exports): ' + key)
            seen.add(key)
            row['source_export'] = str(path)
            row['matched_tasks'] = matched_tasks
            row['atlas_export_commit'] = data.get('atlas_commit')
            row['atlas_pin'] = PIN
            row['failure_type'] = failure(row)
            row['included'] = row['failure_type'] not in ('infra', 'pending_native_grade') and not row.get('excluded', False)
            # Final analysis uses the frozen taxonomy: caps/timeouts precede solved.
            # Keep the historical hidden-test metric for live queue/probe reporting.
            row['strict_solved'] = row.get('category') == 'solved'
            row['primary_solved'] = row['strict_solved'] if strict else bool(row.get('solved_by_tests', row['strict_solved']))
            if row.get('native_grade_pending') and not allow_pending:
                raise ValueError('Final summary blocked by pending native grades')
            if row['included']:
                if not row.get('category') or row.get('wall_s') is None:
                    raise ValueError('Missing grade/wall measurement: ' + key)
                start, end = timestamp(row['started_at']), timestamp(row['ended_at'])
                if end <= start:
                    raise ValueError('Invalid run window: ' + key)
                if row.get('tamper') is True and row['category'] == 'solved':
                    raise ValueError('Tampered run marked solved: ' + key)
            if all(row.get(k) is not None for k in ('tokens_in', 'tokens_cached', 'tokens_out')):
                uncached = row['tokens_in'] - row['tokens_cached']
                if uncached < 0:
                    raise ValueError('Cached input exceeds input: ' + key)
                if row.get('token_accounting') == 'uncached_input_output':
                    for field, expected in [('tokens_uncached_in', uncached),
                            ('tokens_counted', uncached + row['tokens_out']),
                            ('tokens_cumulative', row['tokens_in'] + row['tokens_out'])]:
                        if row.get(field) is not None and row[field] != expected:
                            raise ValueError('Inconsistent ' + field + ': ' + key)
            timing_gaps[row['level']] = timing_gaps.get(row['level'], False) or data.get('timing_contains_repair_gap', False)
            rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[row['level']].append(row)
    samples = []
    for path in sample_paths:
        for line in path.read_text().splitlines():
            sample = json.loads(line)
            sample['_ts'] = timestamp(sample['ts'])
            samples.append(sample)
    summaries = []
    for level, attempts in sorted(groups.items(), key=lambda kv: int(kv[0][1:])):
        group = [r for r in attempts if r['included']]
        basis = group or attempts
        for field in ('config', 'model', 'fixture', 'scored'):
            if len({r.get(field) for r in group}) > 1:
                raise ValueError('Mixed ' + field + ' within ' + level)
        timed_basis = attempts if any(r.get('study_session') for r in attempts) else basis
        timed = [r for r in timed_basis if r.get('started_at') and r.get('ended_at')]
        start = min(timestamp(r['started_at']) for r in timed) if timed else 0
        end = max(timestamp(r['ended_at']) for r in timed) if timed else 0
        # c1 is resumed across droplets: exclude the overnight lifecycle gap.
        sessions = defaultdict(list)
        for row in timed:
            sessions[row.get('study_session')].append(row)
        windows = [(min(timestamp(r['started_at']) for r in rs), max(timestamp(r['ended_at']) for r in rs)) for rs in sessions.values()]
        seconds = sum(b-a for a,b in windows)
        solved = [r for r in group if r['primary_solved']]
        failed = [r for r in group if not r['primary_solved']]
        fixture = any(r.get('fixture') or r.get('scored') is False for r in basis)
        s = dict(pending_mac_grades=sum(bool(r.get('grading_pending')) for r in group),level=level, concurrency=int(level[1:]), runs=len(group), solved=len(solved),
                 success_rate=len(solved) / len(group) if group else None, level_wall_s=seconds,
                 successful_tasks_per_hour=len(solved) * 3600 / seconds if seconds else None,
                 started_at=min((r['started_at'] for r in timed), key=timestamp) if timed else None,
                 ended_at=max((r['ended_at'] for r in timed), key=timestamp) if timed else None,
                 fixture=fixture, scored=not fixture,
                 level_gpu_hours=None if fixture else seconds / 3600,
                 level_gpu_cost_usd=0 if fixture else seconds / 3600 * 1.99,
                 billable_gpu_hours=None, billable_cost_usd=None,
                 infra_attempts=sum(r['failure_type'] == 'infra' for r in attempts),
                 infra_reruns=sum(bool(r.get('retry_of')) for r in attempts),
                 timing_contains_repair_gap=timing_gaps[level],
                 missing_status_runs=sum(r['missing_status'] for r in group) if all(r.get('missing_status') is not None for r in group) else None)
        s.update(solved_rule='tasks-v1 category == solved' if strict else 'hidden tests pass, clean protection, non-infra',
                 tests_passing_at_cutoff=sum(r.get('tests_passed') is True for r in group),
                 clean_tests_passing_at_cutoff=sum(r.get('tests_passed') is True and r.get('tamper') is False for r in group),
                 anecdotal=any(r['anecdotal'] for r in attempts), planned_level_dropped=any(r['planned_level_dropped'] for r in attempts))
        s['measurement_sessions'] = len(sessions)
        if any('native_grade_pending' in r for r in attempts):
            s['pending_native_grades'] = sum(bool(r.get('native_grade_pending')) for r in attempts)
        s['wall_time_basis'] = 'sum of per-study-session attempt windows (infra included)'
        for p in (50, 95):
            s[f'wall_p{p}_s'] = quantile([r['wall_s'] for r in group], p / 100)
        for field in (*TOKEN_FIELDS, 'inference_s', 'wall_s', 'turns', 'tool_calls'):
            s[field] = exact_sum(group, field)
            s['all_attempts_' + field] = exact_sum(attempts, field)
        for field in TOKEN_FIELDS:
            s[field+'_per_task'] = mean(group, field)
        for name, subset in [('solved', solved), ('failed', failed)]:
            for field in ('tokens_in', 'tokens_out', 'turns', 'tool_calls', 'inference_s', 'wall_s'):
                s[f'{name}_{field}_mean'] = mean(subset, field)
        for field in ('model_latency_s', 'ttft_s'):
            series = [r.get(field) for r in group]
            values = [v for vs in series if vs is not None for v in vs]
            if any(vs is None or not vs or any(v is None for v in vs) for vs in series):
                values = []
            for p in (50, 95, 99):
                s[f'{field.removesuffix("_s")}_p{p}_s'] = quantile(values, p / 100)
        for kind in ('wrong_answer', 'timeout', 'turn_cap', 'token_cap', 'context_overflow', 'agent_loop', 'infra', 'other'):
            s['failure_' + kind] = sum(r['failure_type'] == kind for r in attempts)
        window = [r for r in samples if any(a <= r['_ts'] <= b for a,b in windows) and r.get('level',level)==level]
        s['sample_count'] = len(window)
        s.update(level_ttft(samples, level, start, end))
        if len(sessions)>1 or s['anecdotal']:
            # One sampler session cannot measure TTFT for carried-over requests.
            for key in list(s):
                if key.startswith('engine_ttft_'):
                    s[key] = ('anecdotal subset; sampler includes additional historical infra attempt' if s['anecdotal'] else 'multiple sessions; incomplete histograms') if key.endswith('status') else None
        for field in ('peak_vram_mb', 'kv_usage', 'host_cpu_percent', 'host_ram_used_mb'):
            vals = [r[field] for r in window if r.get(field) is not None]
            s[field if field == 'peak_vram_mb' else 'peak_' + field] = max(vals) if vals else None
        summaries.append(s)
    return summaries, sorted(rows, key=lambda r: (int(r['level'][1:]), r['run_id']))


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, separators=(',', ':')) if isinstance(v, (list, dict))
                             else str(v).lower() if isinstance(v, bool) else v for k, v in row.items()})


def write_matched(output_dir, summaries, rows):
    tasks = next((r.get('matched_tasks') for r in rows if r.get('matched_tasks')), None)
    if not tasks:
        return
    selected = [r for r in rows if r['task'] in tasks]
    view = []
    for summary in summaries:
        attempts = [r for r in selected if r['level']==summary['level']]
        group = [r for r in attempts if r['included']]
        present = {r['task'] for r in group}
        solved = sum(bool(r.get('primary_solved', r.get('solved_by_tests', r['category']=='solved'))) for r in group)
        v = dict(level=summary['level'], expected_tasks=tasks, tasks_observed=len(present),
                 missing_tasks=[t for t in tasks if t not in present], complete=len(present)==len(tasks),
                 runs=len(group), solved=solved, success_rate=solved/len(group) if group else None,
                 level_wall_s=summary['level_wall_s'], throughput_basis='matched solved / whole level active wall time',
                 successful_tasks_per_hour=solved*3600/summary['level_wall_s'] if summary['level_wall_s'] else None,
                 infra_attempts=sum(not r['included'] for r in attempts))
        for field in TOKEN_FIELDS:
            v[field] = exact_sum(group,field) if group else None
            v[field+'_per_task'] = mean(group,field)
        for p in (50,95):
            v[f'wall_p{p}_s'] = quantile([r['wall_s'] for r in group],p/100)
        view.append(v)
    write_csv(output_dir/'matched_summary.csv',view)
    write_csv(output_dir/'matched_runs.csv',selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exports', nargs='+', type=Path)
    parser.add_argument('--samples', nargs='*', type=Path, default=[])
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'results')
    parser.add_argument('--allow-fixtures', action='store_true')
    parser.add_argument('--live', action='store_true', help='Operational metrics only; allow pending claims in a separate output directory')
    parser.add_argument('--strict', action='store_true', help='Use the frozen tasks-v1 solved category, with tests-at-cutoff as secondary')
    args = parser.parse_args()
    try:
        summaries, rows = summarize(args.exports, args.samples, args.allow_fixtures, args.live, args.strict)
        if any(r.get('rehearsal') for r in rows):
            if not all(r.get('rehearsal') for r in rows):
                raise ValueError('Cannot mix rehearsal and production rows')
            if not args.output_dir.resolve().is_relative_to((ROOT/'results/rehearsal').resolve()):
                raise ValueError('Rehearsal summaries must stay under results/rehearsal')
        if args.live and args.output_dir.resolve() == (ROOT / 'results').resolve():
            raise ValueError('Use a separate --output-dir for live metrics')
        if args.allow_fixtures and args.output_dir.resolve() == (ROOT / 'results').resolve():
            raise ValueError('Use a separate --output-dir for fixture results')
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(args.output_dir / 'summary.csv', summaries)
        write_csv(args.output_dir / 'runs.csv', rows)
        write_matched(args.output_dir, summaries, rows)
        print(f'Wrote {len(summaries)} levels, {len(rows)} attempts to {args.output_dir}')
        missing = [k for k, v in summaries[0].items() if v is None] if summaries else []
        if missing:
            print('Unavailable fields remain empty: ' + ', '.join(missing), file=sys.stderr)
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
