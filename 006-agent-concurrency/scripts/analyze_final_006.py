#!/usr/bin/env python3
"""Auditable Mac-only final analysis and 007 handoff; no inference or dispatch."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import json
from math import comb, sqrt
from pathlib import Path
from statistics import NormalDist
import sqlite3
import subprocess

from summarize_006 import PIN, summarize, write_csv

ROOT = Path(__file__).resolve().parents[1]
ATLAS = Path('<WORKDIR>/lab/atlas')
LEVELS = ('c16', 'c8', 'c4', 'c1')
PRICE = Decimal('1.99')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def wilson(k, n):
    if not 0 <= k <= n or n == 0: raise ValueError('Invalid Wilson counts')
    z = NormalDist().inv_cdf(.975); p = k/n; scale = 1+z*z/n
    center = (p+z*z/(2*n))/scale
    radius = z*sqrt(p*(1-p)/n+z*z/(4*n*n))/scale
    return [max(0., center-radius), min(1., center+radius)]


def fisher_exact(a, b, c, d):
    """Two-sided fixed-marginal Fisher test; probability-ordering, exact integers."""
    if any(type(v) is not int or v < 0 for v in (a,b,c,d)): raise ValueError('Invalid Fisher table')
    row = a+b; yes = a+c; no = b+d; total = row+c+d
    observed = comb(yes,a)*comb(no,b)
    weights = [comb(yes,x)*comb(no,row-x) for x in range(max(0,row-no), min(row,yes)+1)]
    return sum(w for w in weights if w <= observed)/comb(total,row)


def usage(events):
    """Exact reported-response subtotal; incomplete requests never become zero."""
    calls = {}
    for e in events:
        if e.get('event') in ('request','response'): calls[e['request_id']] = e
    totals = dict(tokens_in=0, tokens_out=0, tokens_cached=0, tokens_uncached_in=0)
    missing = []; measured = 0
    for key, e in calls.items():
        values = [e.get(k) for k in ('tokens_in','tokens_out','tokens_cached')]
        if e['event'] != 'response' or e.get('token_source') != 'proxy' or any(type(v) is not int or v < 0 for v in values):
            missing.append(key); continue
        incoming, outgoing, cached = values
        if cached > incoming: raise ValueError('Cached tokens exceed input')
        for k,v in zip(('tokens_in','tokens_out','tokens_cached','tokens_uncached_in'),(incoming,outgoing,cached,incoming-cached)): totals[k] += v
        measured += 1
    return dict(requests=len(calls), measured_responses=measured, missing_request_ids=missing,
                complete=bool(calls) and not missing, known=totals)


def local_path(path, data):
    if not isinstance(path,str) or '/atlas/data/' not in path: raise ValueError('Unresolved retained evidence path')
    target = (data/path.split('/atlas/data/',1)[1]).resolve()
    if not target.is_relative_to(data.resolve()) or not target.is_file(): raise ValueError('Retained evidence escapes data or is not a file')
    return target


def retained_usage(row, data, dbrows):
    entry = dbrows[row['run_id']]
    trace = local_path(entry['trace_path'], data)
    execution = json.loads(trace.read_text())
    if not execution.get('proxy_log'):
        return dict(complete=False, unavailable='No retained proxy log', known=dict.fromkeys(('tokens_in','tokens_out','tokens_cached','tokens_uncached_in'),0), requests=0, measured_responses=0, missing_request_ids=[], trace=str(trace), trace_sha256=sha(trace))
    proxy = local_path(execution['proxy_log'], data); digest = hashlib.sha256()
    def events():
        with proxy.open('rb') as f:
            for line in f:
                digest.update(line)
                if line.strip(): yield json.loads(line)
    result = usage(events())
    result.update(trace=str(trace), trace_sha256=sha(trace), proxy=str(proxy), proxy_sha256=digest.hexdigest())
    return result


def grading_failure(row, data, root, dbrows):
    if row['category'] != 'infra_error': return None
    paths = sorted((data/'grading').glob('*/'+row['run_id']+'/*/tests/stderr.log'))
    errors = [dict(path=str(p), sha256=sha(p), error=p.read_text()) for p in paths]
    workspace = local_path(dbrows[row['run_id']]['trace_path'],data).parent/'workspace'
    for e in errors:
        if e['error'].strip().startswith('Unsafe snapshot entry: '):
            entry = e['error'].strip().split(': ',1)[1]
            if Path(entry).is_absolute() or '..' in Path(entry).parts: raise ValueError('Unsafe snapshot error entry')
            e.update(unsafe_entry=entry,retained_entry_is_symlink=(workspace/entry).is_symlink())
    snapshot = any(e.get('retained_entry_is_symlink') for e in errors)
    if row['run_id'] == 'c09__qwen38-27b-mi300x__a1162':
        # The original post-session stderr was not synced. REH-006 reproduced
        # the pinned snapshot checker on the exact checkpoint workspace.
        p = root/'results/rehearsal/reh006/infra_replay.txt'
        if 'Unsafe snapshot entry: node_modules/.bin/nanoid' not in p.read_text(): raise ValueError('Missing c09 archive-replay evidence')
        if not (workspace/'node_modules/.bin/nanoid').is_symlink(): raise ValueError('Retained c09 replay entry is no longer a symlink')
        errors.append(dict(path=str(p), sha256=sha(p), error=p.read_text(), retained_entry_is_symlink=True, evidence_kind='archive replay; original grading stderr unavailable'))
        snapshot = True
    return dict(run_id=row['run_id'], level=row['level'], kind='symlink_snapshot' if snapshot else 'execution_infra' if row['end_reason']=='infra' else 'other_grader_infra', evidence=errors)


def exact_window(rows):
    sessions = defaultdict(list)
    for r in rows: sessions[r['study_session']].append(r)
    micros = 0; windows = []
    for session, group in sessions.items():
        first = min(r['started_at'] for r in group); last = max(r['ended_at'] for r in group)
        elapsed = datetime.fromisoformat(last.replace('Z','+00:00'))-datetime.fromisoformat(first.replace('Z','+00:00'))
        us = (elapsed.days*86400+elapsed.seconds)*1000000+elapsed.microseconds
        micros += us; windows.append(dict(study_session=session, started_at=first, ended_at=last, microseconds=us))
    hours = Decimal(micros)/Decimal(3600000000)
    return dict(windows=windows, microseconds=micros, gpu_hours_decimal=str(hours), gpu_hours_fraction=dict(numerator=micros,denominator=3600000000), list_cost_usd_decimal=str(hours*PRICE))


def preemptions(samples, level):
    records = sorted((s for s in samples if s.get('level')==level), key=lambda s:s['ts'])
    before = [s for s in records if s.get('boundary')=='before']; after = [s for s in records if s.get('boundary')=='after']
    observed = [s['preemptions'] for s in records if s.get('preemptions') is not None]
    valid = bool(observed) and all(b>=a for a,b in zip(observed,observed[1:]))
    complete = len(before)==len(after)==1 and before[0]['ts'] < after[0]['ts'] and before[0].get('preemptions') is not None and after[0].get('preemptions') is not None and valid
    return dict(preemptions=after[0]['preemptions']-before[0]['preemptions'] if complete else None,
                observed_preemptions_increase=observed[-1]-observed[0] if valid else None,
                preemptions_status='bracketed counter delta' if complete else 'incomplete boundaries or counter reset; exact delta unavailable')


def audit_inventory(root):
    out = []
    for path in sorted((root/'results/grading/pending').glob('*/request.json')):
        request = json.loads(path.read_text()); returned = root/'results/grading/returned'/path.parent.name
        response = json.loads((returned/'response.json').read_text()); audit = json.loads((returned/'audit.json').read_text())
        claim = response['claim']; classifier = Path(claim['callDirectory'])/'request.json'; call = json.loads(classifier.read_text())
        if not (request['atlas_commit']==response['atlas_commit']==PIN and request['run_id']==response['run_id']
            and response['request_sha256']==sha(path) and request['native_tests_sha256']==sha(path.parent/'native-tests/tests.json')
            and claim['source']=='llm_fallback' and claim['audited'] is True and audit['accepted'] is True
            and audit['expected']==audit['reported']==claim['claim'] and audit['reviewer'] and audit['reason']
            and call['model_id']=='mlx-community/Qwen3.5-4B-4bit' and call['revision']=='0e7ffd5c629ef7719d4cbc04069232580bfa9d9c'
            and call['mlx_lm_version']=='0.31.3' and call['apiSpendUsd']==0): raise ValueError('Unresolved or unbound Mac review: '+str(path))
        out.append(dict(run_id=request['run_id'],level=request['level'],claim=claim['claim'],category=response['category'],
                        request_sha256=sha(path),response_sha256=sha(returned/'response.json'),audit_sha256=sha(returned/'audit.json'),
                        classifier_request_sha256=sha(classifier),reviewer=audit['reviewer'],accepted=True))
    return out


def build(root, atlas=ATLAS):
    if subprocess.check_output(['git','-C',str(atlas),'rev-parse','HEAD'],text=True).strip()!=PIN or subprocess.check_output(['git','-C',str(atlas),'status','--porcelain','--untracked-files=no'],text=True).strip():
        raise ValueError('Pinned ATLAS source differs')
    paths = [root/f'results/atlas/scored/final/{level}/runs.json' for level in LEVELS]
    sample_paths = [p for p in sorted((root/'results/raw').glob('*/samples.jsonl')) if p.parent.name in LEVELS or any(p.parent.name==level+suffix for level in LEVELS for suffix in ('-retry1','-retry2'))]
    summaries, normalized = summarize(paths, sample_paths, strict=True)
    samples = [json.loads(line) for p in sample_paths for line in p.read_text().splitlines()]
    data = root/'results/session7/atlas/data'
    with sqlite3.connect('file:'+str(data/'rocm-recipes-006/atlas.db')+'?mode=ro',uri=True) as db:
        db.row_factory = sqlite3.Row; dbrows = {r['run_id']:dict(r) for r in db.execute('SELECT * FROM runs')}
    history = json.loads(gzip.decompress((root/'inputs/session4/history.json.gz').read_bytes()))
    historical = {e['row']['run_id']:e['grade'] for e in history['entries'] if e['grade']}
    inventory = audit_inventory(root); ledger = []; failures = []; output = []
    for level in LEVELS:
        report = json.loads(paths[LEVELS.index(level)].read_text())
        if not report['complete'] or not report['execution_complete'] or report.get('pending_mac_grades') or report.get('pending_native_grades'):
            raise ValueError('Final report still pending: '+level)
        rows = [r for r in normalized if r['level']==level]; summary = dict(next(s for s in summaries if s['level']==level))
        included = [r for r in rows if r['included']]
        if len({r['task'] for r in included})!=len(included): raise ValueError('Multiple scored verdicts for one task')
        coverage = []
        for row in rows:
            u = usage(historical[row['run_id']]['evidence']['raw']) if level=='c1' else retained_usage(row,data,dbrows)
            if level=='c1': u['source']='inputs/session4/history.json.gz';u['source_sha256']=sha(root/u['source'])
            u.update(run_id=row['run_id'],level=level);ledger.append(u);coverage.append(u)
            failure = grading_failure(row,data,root,dbrows)
            if failure: failures.append(failure)
        known = {k:sum(u['known'][k] for u in coverage) for k in coverage[0]['known']}
        full = all(u['complete'] for u in coverage)
        summary.update(attempts=len(rows), graded_tasks=len(included), strict_solved=summary['solved'],wilson95=wilson(summary['solved'],len(included)),
            taxonomy=dict(sorted(Counter(r['category'] for r in rows).items())),grader_infra_symlink=sum(f['level']==level and f['kind']=='symlink_snapshot' for f in failures),
            unknown_verdict_tasks=sorted({r['task'] for r in rows}-{r['task'] for r in included}),
            accounting=exact_window(rows),token_total_complete=full,token_incomplete_attempts=sum(not u['complete'] for u in coverage),
            missing_usage_requests=sum(len(u['missing_request_ids']) for u in coverage),measured_usage_responses=sum(u['measured_responses'] for u in coverage),
            completed_response_tokens=known,exact_all_attempt_tokens={k:v if full else None for k,v in known.items()},
            tokens_per_solved=(known['tokens_uncached_in']+known['tokens_out'])/summary['solved'] if full and summary['solved'] else None,
            tokens_per_solved_lower_bound=(known['tokens_uncached_in']+known['tokens_out'])/summary['solved'] if summary['solved'] else None)
        solved = [r for r in included if r['strict_solved']]
        for field in ('tokens_uncached_in','tokens_out'):
            summary['solved_only_mean_'+field] = sum(r[field] for r in solved)/len(solved) if solved and all(r.get(field) is not None for r in solved) else None
        summary.update(preemptions(samples,level))
        if summary['anecdotal']:
            summary.update(preemptions=None,preemptions_status='Historical sampler includes c22 infra, outside the anecdotal n=3 subset')
        output.append(summary)
    main = {s['level']:s for s in output if s['level']!='c1'}
    comparisons = []
    for a,b in [('c16','c8'),('c16','c4'),('c8','c4')]:
        x,y = main[a],main[b];table = [[x['solved'],x['runs']-x['solved']],[y['solved'],y['runs']-y['solved']]]
        comparisons.append(dict(levels=[a,b],table=table,two_sided_p=fisher_exact(*table[0],*table[1]),adjustment='none; descriptive comparisons of overlapping frozen task sets'))
    result = dict(atlas_commit=PIN,source_commit='7235813',list_price_usd_per_gpu_hour='1.99',
                  solved_rule='Frozen tasks-v1 category == solved; timeout/turn/token caps, tamper and infra are not solved',
                  tests_at_cutoff_rule='testsPassed == true on scored non-infra attempts; includes tampered artifacts, separately reported clean count',
                  denominator_rule='One non-infra verdict per task; unresolved grader-infra tasks excluded, not failed',
                  token_rule='Exact full-level totals are null if any request usage is missing. Completed-response subtotals are exact for the measured subset and lower bounds for the full level; infra retries included.',
                  gpu_hours_rule='First attempt start through last attempt end within each level/session, including infra retries and gaps; setup/probe/cleanup excluded',
                  exact_token_cost_comparison_ready=all(s['token_total_complete'] for s in output),
                  recorded_total_billable_gpu_hours=json.loads((root/'STATE.json').read_text())['gpu_hours_used_total'],
                  levels=output,fisher_exact=comparisons,mac_reviews=inventory,grader_infra=failures)
    save(root/'results/final_analysis.json',result);save(root/'results/token_coverage.json',ledger)
    write_csv(root/'results/final_summary.csv',output)
    handoff = root/'006-handoff';handoff.mkdir(exist_ok=True)
    save(handoff/'metrics.json',result)
    compact = []
    for s in output:
        item=dict(level=s['level'],scope='anecdotal n=3; remainder dropped' if s['anecdotal'] else 'main',
                  attempts=s['attempts'],graded_tasks=s['runs'],strict_solved=s['solved'],tests_passing_at_cutoff=s['tests_passing_at_cutoff'],
                  gpu_hours=s['accounting']['gpu_hours_decimal'],gpu_window_microseconds=s['accounting']['microseconds'],gpu_hours_denominator=3600000000,
                  list_price_usd_per_gpu_hour='1.99',list_cost_usd=s['accounting']['list_cost_usd_decimal'],
                  tokens_complete=s['token_total_complete'],tokens_per_solved=s['tokens_per_solved'],tokens_per_solved_lower_bound=s['tokens_per_solved_lower_bound'],missing_usage_requests=s['missing_usage_requests'])
        item.update(s['exact_all_attempt_tokens'])
        item.update({'completed_response_'+k:v for k,v in s['completed_response_tokens'].items()})
        compact.append(item)
    write_csv(handoff/'per_level.csv',compact)
    for source,name in [(atlas/'tasks/CHECKSUMS','tasks-CHECKSUMS'),(atlas/'tasks/FROZEN.json','tasks-FROZEN.json'),
                        (atlas/'config/run-configs/qwen38-27b-mi300x.ts','run-config.ts'),(root/'notes/engine_choice.json','engine_choice.json'),
                        (root/'results/droplet_logs/current_server.json','served_engine.json'),
                        (root/'results/token_coverage.json','token_coverage.json'),(root/'results/matched_summary.csv','matched_summary.csv'),
                        (root/'results/matched_runs.csv','matched_runs.csv'),(root/'results/grading/completion_audit.json','completion_audit.json')]:
        (handoff/name).write_bytes(source.read_bytes())
    sources = paths+sample_paths+[root/'results/token_coverage.json',root/'results/session4/progress.json',root/'inputs/session4/history.json.gz']
    sources += [root/'scripts'/name for name in ('finalize_006.py','summarize_006.py','analyze_final_006.py','ttft_006.py')]
    save(handoff/'sources.json',{str(p.relative_to(root)):sha(p) for p in sources})
    save(handoff/'checksums.json',{p.name:sha(p) for p in sorted(handoff.iterdir()) if p.is_file() and p.name != 'checksums.json'})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--atlas',type=Path,default=ATLAS);args=p.parse_args()
    value=build(args.root,args.atlas)
    print(json.dumps([dict(level=r['level'],solved=r['solved'],n=r['runs'],wilson95=r['wilson95'],tests_passing_at_cutoff=r['tests_passing_at_cutoff'],gpu_hours=r['accounting']['gpu_hours_decimal'],known_tokens=r['completed_response_tokens'],exact_tokens_available=r['token_total_complete']) for r in value['levels']],indent=2))
