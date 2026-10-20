#!/usr/bin/env python3
"""Validate public measurements, exclusion policy and checksums without a harness."""
import csv,hashlib,json,math,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from summarize_006 import summarize

def fisher(a,b,c,d):
 row=a+b;yes=a+c;no=b+d;total=row+c+d
 weight=lambda x:math.comb(yes,x)*math.comb(no,row-x)
 return sum(weight(x) for x in range(max(0,row-no),min(row,yes)+1) if weight(x)<=weight(a))/math.comb(total,row)
def main():
 reports=[ROOT/f'results/atlas/scored/final/{l}/runs.json' for l in ('c16','c8','c4','c1')]
 summaries,rows=summarize(reports,list((ROOT/'results/raw').glob('*/samples.jsonl')),strict=True)
 assert len(rows)==104 and sum(r['included'] for r in rows)==90
 analysis=json.loads((ROOT/'results/final_analysis.json').read_text())
 with (ROOT/'007-inputs/per_level.csv').open() as f:handoff={r['level']:r for r in csv.DictReader(f)}
 engines=json.loads((ROOT/'results/analysis/engine_input_totals.json').read_text())
 for s in summaries:
  a=next(x for x in analysis['levels'] if x['level']==s['level']);h=handoff[s['level']]
  assert s['solved']==a['solved']==int(h['strict_solved'])
  assert s['runs']==a['graded_tasks']==int(h['graded_tasks'])
  assert abs(s['level_gpu_hours']-int(h['gpu_window_microseconds'])/int(h['gpu_hours_denominator']))<1e-9
  assert s['tests_passing_at_cutoff']==a['tests_passing_at_cutoff']
  z=1.959963984540054;p=s['solved']/s['runs'];den=1+z*z/s['runs'];center=(p+z*z/(2*s['runs']))/den;rad=z*math.sqrt(p*(1-p)/s['runs']+z*z/(4*s['runs']**2))/den
  assert max(abs(x-y) for x,y in zip(a['wilson95'],[center-rad,center+rad]))<1e-12
  assert not s.get('pending_native_grades') and not s['pending_mac_grades']
 for t in analysis['fisher_exact']:
  table=t['table'];assert abs(fisher(*table[0],*table[1])-t['two_sided_p'])<1e-12
 for e in engines['levels']:
  assert e['prompt_tokens']-e['cached_input_tokens']==e['uncached_input_tokens']
  h=handoff[e['level']]
  assert all(int(h['engine_'+k])==e[k] for k in ('prompt_tokens','cached_input_tokens','uncached_input_tokens'))
 sensitivity=json.loads((ROOT/'results/analysis/symlink_sensitivity.json').read_text())
 assert len(sensitivity['attempts'])==13 and sum(x['tests_passed'] for x in sensitivity['attempts'])==4
 assert not any(x['strict_solved'] for x in sensitivity['attempts'])
 for lev in sensitivity['levels']:
  a=next(x for x in analysis['levels'] if x['level']==lev['level']);assert lev['official']['solved']==lev['sensitivity']['solved']==a['solved'];assert lev['sensitivity']['graded_tasks']==30
 banned_name=re.compile(r'(?i)(?:^|/)(?:notes|escalations|prompts|social)(?:/|$)|(?:^|/)(?:PLAN[^/]*\.md|STATE\.json|config\.env|ARTICLE[^/]*)$')
 banned_text=re.compile(r'(?i)/Volumes/|/Users/|evooffice|\bclaude\b|\bluna\b|\bsol\b|SHA256:[A-Za-z0-9+/]{43}(?:=)?(?![A-Za-z0-9+/])')
 ip=re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
 for p in ROOT.rglob('*'):
  if not p.is_file() or '__pycache__' in p.parts or p.name=='validate.py':continue
  relative=str(p.relative_to(ROOT));assert not banned_name.search(relative),relative
  text=p.read_text();assert not banned_text.search(text),relative
  assert all(x in ('0.0.0.0','127.0.0.1') for x in ip.findall(text)),relative
  if p.suffix=='.json':json.loads(text)
 sums=ROOT/'SHA256SUMS'
 if sums.exists():
  for line in sums.read_text().splitlines():
   h,name=line.split('  ',1);assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name
 print('VALIDATION OK: 104 attempts; strict counts, Wilson/Fisher, GPU windows, engine inputs, sensitivity and public scrub verified.')
if __name__=='__main__':main()
