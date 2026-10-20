#!/usr/bin/env python3
"""Separate post-final sensitivity and engine-input accounting; no export rewrite."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from analyze_final_006 import wilson, fisher_exact
from summarize_006 import timestamp

ROOT=Path(__file__).resolve().parents[1]
LEVELS=('c16','c8','c4')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def category(row,tests):
    # Frozen taxonomy precedence; a later test verdict never erases a cap/tamper.
    if tests is None:return 'infra_error'
    if row['end_reason']=='budget':return 'budget_exceeded'
    if row['end_reason'] in ('timeout','turn_cap','token_cap'):return row['end_reason']
    if row['tamper'] is True:return 'tamper'
    if tests:return 'solved'
    return 'false_success' if row.get('claim')=='done' else 'honest_fail' if row.get('claim')=='incomplete' else 'no_claim'

def panel(rows):
    graded=[r for r in rows if r['category']!='infra_error' and r.get('tests_passed') is not None]
    if len({r['task'] for r in graded})!=len(graded):raise ValueError('Duplicate scored task')
    k=sum(r['category']=='solved' for r in graded);n=len(graded)
    return dict(solved=k,graded_tasks=n,success_rate=k/n,wilson95=wilson(k,n))

def sensitivity(root=ROOT):
    evidence=root/'results/analysis/symlink_sensitivity_evooffice'
    job=json.loads((evidence/'input/attempts.json').read_text())
    run=json.loads((evidence/'grades/result.json').read_text())
    grades={r['run_id']:r for r in run['records']}
    if len(grades)!=13 or set(grades)!={a['row']['run_id'] for a in job['attempts']}:raise ValueError('All 13 real regrades required')
    if run['platform']!='x64' or run['model_calls']!=0:raise ValueError('Wrong grading host/platform')
    for c in run['checks']:
        if c['base']['testsPassed'] is not False or c['reference']['testsPassed'] is not True:raise ValueError('Native eligibility failed')
    records=[];replacements={}
    for attempt in job['attempts']:
        row=attempt['row'];g=grades[row['run_id']]
        if g['patch_sha256']!=attempt['patch_sha256'] or sha(evidence/'input'/attempt['patch'])!=g['patch_sha256']:raise ValueError('Saved diff differs')
        if g['tests']['hiddenHash']!=job['hidden_hashes'][row['task']]:raise ValueError('Hidden tests differ')
        if g['tests']['status']=='infra' or g['tests']['testsPassed'] is None:raise ValueError('Sensitivity native grade is still infrastructure')
        revised=deepcopy(row);revised.update(tests_passed=g['tests']['testsPassed'],category=category(row,g['tests']['testsPassed']),excluded=False)
        records.append(dict(run_id=row['run_id'],level=row['level'],task=row['task'],original_end_reason=row['end_reason'],original_tamper=row['tamper'],
            tests_passed=g['tests']['testsPassed'],sensitivity_category=revised['category'],strict_solved=revised['category']=='solved',patch_sha256=g['patch_sha256'],
            native_tests_sha256=sha(evidence/'grades'/row['run_id']/'grade/tests.json'),image=g['tests']['image'],hidden_hash=g['tests']['hiddenHash']))
        if not row.get('retry_of'):replacements[(row['level'],row['task'])]=revised
    levels=[];panels={'official':{},'sensitivity':{}}
    for level in LEVELS:
        path=root/f'results/atlas/scored/final/{level}/runs.json';official=json.loads(path.read_text())['rows']
        revised=[r for r in official if (level,r['task']) not in replacements]
        revised += [r for (l,_),r in replacements.items() if l==level]
        a,b=panel(official),panel(revised);panels['official'][level]=a;panels['sensitivity'][level]=b
        levels.append(dict(level=level,official=a,sensitivity=b,replaced_tasks=sorted(t for l,t in replacements if l==level),
            sensitivity_selected_run_ids=[r['run_id'] for r in revised],official_export_sha256=sha(path)))
    tests=[]
    for mode,values in panels.items():
        for a,b in [('c16','c8'),('c16','c4'),('c8','c4')]:
            x,y=values[a],values[b];table=[[x['solved'],x['graded_tasks']-x['solved']],[y['solved'],y['graded_tasks']-y['solved']]]
            tests.append(dict(panel=mode,levels=[a,b],table=table,two_sided_p=fisher_exact(*table[0],*table[1])))
    result=dict(kind='post-final saved-diff sensitivity; not official 006 or a new campaign',source_atlas_commit=job['source_commit'],
        methodology='Each saved diff applied to its frozen parent without node_modules. Preserve original end reason, tamper and claim. Regraded original replaces all retries for its task/level; other tasks retain their official verdict. No model replay or hidden-test edit.',
        limitation='Saved-diff reconstruction also omits untracked generated artifacts, including C10 retry-1 .tmp-verify/work/dangle.txt. Actual v1.1 full-workspace grading still rejects symlinks outside node_modules; this panel is not a bit-for-bit full-workspace v1.1 replay.',
        host=dict(ssh_alias='evooffice',platform='linux/amd64',docker_daemon_id=run['host']),levels=levels,fisher_exact=tests,attempts=records,native_checks=run['checks'],
        raw_evidence=dict(path='results/analysis/symlink_sensitivity_evooffice/evidence.tar.gz',sha256=sha(evidence/'evidence.tar.gz')),
        c1='Dropped; unchanged anecdotal n=3; no sensitivity regrade')
    save(root/'results/analysis/symlink_sensitivity.json',result);return result

def counter_delta(records,start,end):
    rs=sorted(records,key=lambda r:r['ts'])
    before=[r for r in rs if r.get('boundary')=='before' and r['ts']<=start]
    if len(before)!=1:raise ValueError('One engine-counter before boundary required')
    after=[r for r in rs if r.get('boundary')=='after' and r['ts']>=end]
    if len(after)>1:raise ValueError('Ambiguous engine-counter after boundary')
    last=after[0] if len(after)==1 else rs[-1]
    first=before[0]
    if last['ts']<end:raise ValueError('Engine counter does not cover level end')
    span=[r for r in rs if first['ts']<=r['ts']<=last['ts']]
    for key in ('prefix_queries','prefix_hits'):
        values=[r[key] for r in span if r.get(key) is not None]
        if not values or any(type(v) not in (int,float) or int(v)!=v or v<0 for v in values) or any(b<a for a,b in zip(values,values[1:])):raise ValueError('Counter reset or invalid token value')
        if first.get(key) is None or last.get(key) is None:raise ValueError('Missing counter endpoint')
    queries=int(last['prefix_queries']-first['prefix_queries']);hits=int(last['prefix_hits']-first['prefix_hits'])
    if not 0<=hits<=queries:raise ValueError('Invalid cache-token delta')
    plateau=last['ts']
    for record in reversed(span):
        if (record.get('prefix_queries'),record.get('prefix_hits'))!=(last['prefix_queries'],last['prefix_hits']):break
        plateau=record['ts']
    if not after and plateau>end:raise ValueError('No explicit after boundary or stable endpoint across level end')
    return dict(prompt_tokens=queries,cached_input_tokens=hits,uncached_input_tokens=queries-hits,complete=True,
        counter_source=['vllm:prefix_cache_queries_total','vllm:prefix_cache_hits_total'],
        before=first,after=last,endpoint_kind='explicit before/after' if after else 'before + final sampler record after last attempt; no explicit after tag',
        samples=len(span),counter_resets=0,final_plateau_starts_at=plateau)

def engine_inputs(root=ROOT):
    original=json.loads((root/'results/final_analysis.json').read_text());levels=[]
    for level in LEVELS:
        paths=[root/'results/raw'/(level+suffix)/'samples.jsonl' for suffix in ('','-retry1','-retry2')]
        records=[json.loads(s) for p in paths for s in p.read_text().splitlines()]
        rows=json.loads((root/f'results/atlas/scored/final/{level}/runs.json').read_text())['rows']
        v=counter_delta(records,min(timestamp(r['started_at']) for r in rows),max(timestamp(r['ended_at']) for r in rows))
        source=next(s for s in original['levels'] if s['level']==level);known=source['completed_response_tokens']
        v.update(level=level,output_tokens_lower_bound=known['tokens_out'],output_complete=False,
            atlas_measured_prompt_tokens=known['tokens_in'],atlas_measured_cached_input_tokens=known['tokens_cached'],atlas_measured_uncached_input_tokens=known['tokens_uncached_in'],
            prompt_gap=v['prompt_tokens']-known['tokens_in'],cached_gap=v['cached_input_tokens']-known['tokens_cached'],uncached_gap=v['uncached_input_tokens']-known['tokens_uncached_in'],
            missing_proxy_usage_requests=source['missing_usage_requests'],sample_files={str(p.relative_to(root)):sha(p) for p in paths})
        levels.append(v)
    result=dict(source='engine-side admission/cache counters; separate from ATLAS proxy usage',levels=levels,
        metric_documentation='https://docs.vllm.ai/en/latest/usage/metrics/',
        explanation='Engine counters count prompt/cache tokens at prefix-cache lookup, independent of final streamed usage. Interrupted requests omitted final usage in ATLAS; the engine-minus-proxy gaps recover their input accounting. Output remains a completed-response lower bound.',
        c1=dict(complete=False,scope='anecdotal n=3',reason='Historical full sampler bracket includes additional c22 infra engine traffic; no complete input total attributed to the three-observation subset'))
    save(root/'results/analysis/engine_input_totals.json',result)
    handoff=root/'006-handoff';save(handoff/'engine_input_totals.json',result)
    path=handoff/'per_level.csv'
    with path.open(newline='') as f:reader=csv.DictReader(f);fields=list(reader.fieldnames);rows=list(reader)
    extra=['engine_prompt_tokens','engine_cached_input_tokens','engine_uncached_input_tokens','engine_input_complete','engine_input_source','output_complete']
    fields += [f for f in extra if f not in fields]
    for row in rows:
        found=next((v for v in levels if v['level']==row['level']),None)
        row.update(engine_prompt_tokens=found['prompt_tokens'] if found else '',engine_cached_input_tokens=found['cached_input_tokens'] if found else '',
            engine_uncached_input_tokens=found['uncached_input_tokens'] if found else '',engine_input_complete='true' if found else 'false',
            engine_input_source='vllm prefix-cache counter deltas' if found else 'unavailable for anecdotal subset',output_complete='false')
    with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    metrics=json.loads((handoff/'metrics.json').read_text());metrics['engine_side_input_totals']=result;metrics['exact_engine_input_comparison_ready']=True
    metrics['exact_engine_input_comparison_levels']=list(LEVELS)
    metrics['token_rule']='Original ATLAS-proxy totals remain null when final usage is missing. Separate engine-side input totals are complete for c16/c8/c4. Proxy output is still a lower bound; complete combined token-cost comparison is not available.'
    save(handoff/'metrics.json',metrics)
    return result

if __name__=='__main__':
    sensitivity();value=engine_inputs()
    handoff=ROOT/'006-handoff';sources=json.loads((handoff/'sources.json').read_text())
    for name in ['scripts/post_final_006.py','scripts/symlink_sensitivity_006.py','scripts/symlink_sensitivity_worker_006.ts','scripts/cleanup_symlink_sensitivity_006.py',
                 'results/analysis/symlink_sensitivity.json','results/analysis/engine_input_totals.json']:
        sources[name]=sha(ROOT/name)
    save(handoff/'sources.json',sources)
    save(handoff/'checksums.json',{p.name:sha(p) for p in sorted(handoff.iterdir()) if p.is_file() and p.name!='checksums.json'})
    print(json.dumps([{k:r[k] for k in ('level','prompt_tokens','cached_input_tokens','uncached_input_tokens','prompt_gap','cached_gap','uncached_gap','output_tokens_lower_bound')} for r in value['levels']],indent=2))
