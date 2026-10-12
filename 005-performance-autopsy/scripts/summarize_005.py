#!/usr/bin/env python3
"""Rebuild 005's results/summary.csv and results/deltas.csv from raw run folders.

summary.csv: one row per run (004's columns plus the 005 fields).
deltas.csv:  for each config, knob set and benchmark cell, the % change of each metric vs the
             same cell on the B (baseline) server, plus the baseline noise band from the B repeat.
"""
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PCT = [f'{m}_{p}_ms' for m in ('ttft', 'tpot', 'itl', 'e2el') for p in ('p50', 'p95', 'p99')]
COLS = (['run_id', 'recipe', 'workload', 'knob_set', 'model', 'engine', 'cfg', 'kv_cache_dtype', 'quant',
         'max_model_len', 'input_len', 'output_len', 'concurrency', 'num_prompts', 'seed', 'completed',
         'failed', 'mean_output_tokens'] + PCT +
        ['decode_tok_per_s', 'output_tok_per_s', 'total_tok_per_s', 'kv_cache_tokens',
         'max_concurrency_at_max_len', 'peak_vram_mb', 'peak_kv_usage', 'preemptions',
         'prefix_cache_hit_rate', 'engine_version', 'image_digest', 'aiter_version', 'server_args', 'status'])
DELTA_METRICS = ['ttft_p50_ms', 'ttft_p95_ms', 'ttft_p99_ms', 'tpot_p50_ms', 'tpot_p95_ms', 'itl_p50_ms',
                 'e2el_p50_ms', 'e2el_p95_ms', 'decode_tok_per_s', 'output_tok_per_s', 'peak_kv_usage',
                 'preemptions', 'prefix_cache_hit_rate']
CFG_KNOB = re.compile(r'-(VD|VT|SD|SX|LC1|LC4)-(B|K1|K2|K3|T)(?=-|$)')


def client_result(d):
    """vLLM bench's own result JSON in a run folder (fallback when meta.json lacks a value)."""
    for f in sorted(d.rglob('*.json')):
        if f.name == 'meta.json':
            continue
        try:
            obj = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(obj, dict) and ('completed' in obj or 'median_ttft_ms' in obj):
            return obj
    return {}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cell_key(run_id):
    """Run ID with config and knob removed: the same benchmark cell across servers."""
    return CFG_KNOB.sub('', run_id)


def main():
    rows = []
    for p in sorted((ROOT / 'results/raw').glob('*/*/meta.json')):
        m = json.loads(p.read_text())
        row = {k: m.get(k) for k in COLS}
        if m.get('recipe') in ('L1', 'L2'):
            x = client_result(p.parent)
            for name in ('ttft', 'tpot', 'itl', 'e2el'):
                for ours, theirs in ((f'{name}_p50_ms', f'median_{name}_ms'), (f'{name}_p95_ms', f'p95_{name}_ms'),
                                     (f'{name}_p99_ms', f'p99_{name}_ms')):
                    if row.get(ours) is None:
                        row[ours] = x.get(theirs)
            if row.get('output_tok_per_s') is None:
                row['output_tok_per_s'] = x.get('output_throughput')
            if row.get('total_tok_per_s') is None:
                row['total_tok_per_s'] = x.get('total_token_throughput')
            itl = num(row.get('itl_p50_ms'))
            row['decode_tok_per_s'] = 1000 / itl if itl else None
            if m.get('status') in ('ok', 'partial', 'short_output') and row.get('ttft_p50_ms') is None:
                print(f'{p}: no TTFT found; client keys: {sorted(x)}', file=sys.stderr)
        elif m.get('recipe') == 'L0':
            cp = p.parent / 'capacity.json'
            if cp.exists():
                c = json.loads(cp.read_text())
                row['kv_cache_tokens'] = c.get('kv_cache_tokens')
                row['max_concurrency_at_max_len'] = c.get('max_concurrency_at_max_len')
        rows.append(row)

    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    with (out / 'summary.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({k: ('' if v is None else v) for k, v in r.items()} for r in rows)

    bench = [r for r in rows if r.get('recipe') in ('L1', 'L2') and r.get('status') in ('ok', 'partial', 'short_output')
             and not str(r.get('run_id', '')).endswith('-prewarm')]
    base = {(r['cfg'], cell_key(r['run_id'])): r for r in bench if r.get('knob_set') == 'B'}
    deltas = []
    for r in bench:
        if r.get('knob_set') == 'B':
            continue
        key = cell_key(r['run_id'])
        b = base.get((r['cfg'], key))
        if b is None:
            continue
        rep = base.get((r['cfg'], key + '-r2'))  # B repeat of the same cell, if one exists
        for metric in DELTA_METRICS:
            bv, rv = num(b.get(metric)), num(r.get(metric))
            delta = (rv - bv) / bv * 100 if bv not in (None, 0) and rv is not None else None
            noise = None
            if rep is not None and bv not in (None, 0) and num(rep.get(metric)) is not None:
                noise = abs(num(rep.get(metric)) - bv) / bv * 100
            deltas.append({'cfg': r['cfg'], 'knob_set': r['knob_set'], 'workload': r.get('workload'),
                           'cell': key, 'metric': metric, 'baseline': bv, 'value': rv,
                           'delta_pct': delta, 'baseline_noise_pct': noise})
    with (out / 'deltas.csv').open('w', newline='') as f:
        fields = ['cfg', 'knob_set', 'workload', 'cell', 'metric', 'baseline', 'value', 'delta_pct', 'baseline_noise_pct']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: ('' if v is None else v) for k, v in d.items()} for d in deltas)
    print(f'{len(rows)} rows -> results/summary.csv; {len(deltas)} deltas -> results/deltas.csv')


if __name__ == '__main__':
    main()
