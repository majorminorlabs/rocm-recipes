#!/usr/bin/env python3
"""Rebuild results/summary.csv from raw recipe metadata."""
import csv, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
COLS='run_id recipe model kv_cache_dtype max_model_len input_len output_len concurrency num_prompts ttft_p50_ms ttft_p99_ms itl_p50_ms itl_p99_ms output_tok_per_s total_tok_per_s kv_cache_tokens max_concurrency_at_max_len needle_correct needle_total needle_errors distractor_hits mean_prompt_tokens status'.split()
KEYS={'ttft_p50_ms':'median_ttft_ms','ttft_p99_ms':'p99_ttft_ms','itl_p50_ms':'median_itl_ms','itl_p99_ms':'p99_itl_ms','output_tok_per_s':'output_throughput','total_tok_per_s':'total_token_throughput'}
def main():
 rows=[]
 for p in sorted((ROOT/'results/raw').glob('*/*/meta.json')):
  m=json.loads(p.read_text()); row={k:m.get(k) for k in COLS}; recipe=m.get('recipe'); d=p.parent
  if recipe in ('L1','L2'):
   files=[x for x in d.glob('*.json') if x.name not in ('meta.json',)]; data={}
   for f in files:
    try: data.update(json.loads(f.read_text()))
    except (ValueError,OSError): pass
   for dst,src in KEYS.items():
    if src in data: row[dst]=data[src]
    else: print(f'{p}: missing {src}; available keys: {sorted(data)}',file=sys.stderr)
  elif recipe=='L0':
   cp=d/'capacity.json'
   if cp.exists():
    c=json.loads(cp.read_text()); row['kv_cache_tokens']=c.get('kv_cache_tokens'); row['max_concurrency_at_max_len']=c.get('max_concurrency_at_max_len')
  elif recipe in ('L3','L3H'):
   for k in ('needle_correct','needle_total','needle_errors','distractor_hits','mean_prompt_tokens'): row[k]=m.get(k)
  rows.append(row)
 out=ROOT/'results/summary.csv'; out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=COLS); w.writeheader(); w.writerows(rows)
if __name__=='__main__': main()
