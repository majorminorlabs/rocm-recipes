#!/usr/bin/env python3
"""Rebuild results/summary.csv from raw run folders (004: multi-engine)."""
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COLS = ('run_id recipe model engine cfg kv_cache_dtype max_model_len input_len output_len concurrency '
        'num_prompts seed completed failed mean_output_tokens ttft_p50_ms ttft_p99_ms itl_p50_ms itl_p99_ms '
        'decode_tok_per_s output_tok_per_s total_tok_per_s kv_cache_tokens max_concurrency_at_max_len '
        'needle_correct needle_total needle_errors distractor_hits mean_prompt_tokens engine_version '
        'image_digest aiter_version status').split()
KEYS = {'ttft_p50_ms': 'median_ttft_ms', 'ttft_p99_ms': 'p99_ttft_ms', 'itl_p50_ms': 'median_itl_ms',
        'itl_p99_ms': 'p99_itl_ms', 'output_tok_per_s': 'output_throughput',
        'total_tok_per_s': 'total_token_throughput'}


def client_result(d):
    """The vLLM bench result JSON in a run folder (any .json that is not meta.json)."""
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


def main():
    rows = []
    for p in sorted((ROOT / 'results/raw').glob('*/*/meta.json')):
        m = json.loads(p.read_text())
        row = {k: m.get(k) for k in COLS}
        recipe, d = m.get('recipe'), p.parent
        if recipe in ('L1', 'L2'):
            data = client_result(d)
            for dst, src in KEYS.items():
                if src in data:
                    row[dst] = data[src]
                elif m.get('status') in ('ok', 'partial', 'short_output'):
                    print(f'{p}: missing {src}; available keys: {sorted(data)}', file=sys.stderr)
            if row.get('itl_p50_ms'):
                row['decode_tok_per_s'] = 1000 / row['itl_p50_ms']
        elif recipe == 'L0':
            cp = d / 'capacity.json'
            if cp.exists():
                c = json.loads(cp.read_text())
                row['kv_cache_tokens'] = c.get('kv_cache_tokens')
                row['max_concurrency_at_max_len'] = c.get('max_concurrency_at_max_len')
        rows.append(row)
    out = ROOT / 'results/summary.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({k: ('' if v is None else v) for k, v in r.items()} for r in rows)
    print(f'{len(rows)} rows -> {out}')


if __name__ == '__main__':
    main()
