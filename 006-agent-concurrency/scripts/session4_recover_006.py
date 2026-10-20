#!/usr/bin/env python3
"""Offline REH-005 export and bound checkpoint restore; never uses cloud APIs."""
import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
RUN='c09__qwen38-27b-mi300x__a1162'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')


def verify_checkpoint(root):
    scope=root/'results/session4';manifest=scope/'resume.json'
    spec=json.loads(manifest.read_text())
    for name,digest in spec['files'].items():
        if Path(name).name!=name or sha(scope/name)!=digest:raise ValueError('Resume checkpoint changed: '+name)
    if 'pending_native_snapshot' in spec and hashlib.sha256(spec['pending_native_snapshot'].encode()).hexdigest()!=spec['files']['pending_native.json']:
        raise ValueError('Checkpoint pending snapshot differs from its bound hash')
    return spec


def completed_transition(previous,current):
    if set(previous)!=set(current) or set(current)!={'runs'} or len(previous['runs'])!=len(current['runs']):
        raise ValueError('Pending native registry shape changed')
    changed=[]
    for old,new in zip(previous['runs'],current['runs']):
        if old==new:continue
        expected=dict(old,status='complete',grade_record=new.get('grade_record'),grading_host=new.get('grading_host'))
        if old.get('status')!='pending' or new.get('status')!='complete' or expected!=new:
            raise ValueError('Only pending -> complete native grading is allowed; execution/proof fields are immutable')
        host=new.get('grading_host',{});run=old['row']['run_id']
        grade=Path(str(new.get('grade_record','')))
        if set(host)!={'daemonId','platform'} or host.get('platform')!='linux/amd64' or not isinstance(host.get('daemonId'),str) or not host['daemonId'] or not grade.is_absolute() or '..' in grade.parts or not str(grade).endswith('/atlas/data/grading/post-session/'+run+'/grade.json'):
            raise ValueError('Completed native grade needs its amd64 host and retained grade reference')
        changed.append(run)
    if not changed:raise ValueError('No pending -> complete native grade transition')
    return changed


def completed_report(previous,current,registry):
    expected=copy.deepcopy(previous);items={r['row']['run_id']:r for r in registry['runs']}
    if [r['run_id'] for r in previous['rows']]!=[r['run_id'] for r in current['rows']]:
        raise ValueError('Completed report run identities/order changed')
    for old,new in zip(expected['rows'],current['rows']):
        if old==new:continue
        item=items.get(old['run_id'],{})
        if not old.get('native_grade_pending') or item.get('status')!='complete':raise ValueError('Unrelated report row changed')
        tests,tamper=new.get('tests_passed'),new.get('tamper');category=new.get('category')
        if type(tests) not in (bool,type(None)) or type(tamper) not in (bool,type(None)) or category not in ('infra_error','timeout','turn_cap','token_cap','tamper','solved','false_success','honest_fail','no_claim','budget_exceeded'):
            raise ValueError('Invalid completed native verdict')
        if tests is None and category!='infra_error':raise ValueError('Unavailable native tests must remain infra')
        old.update(native_grade_pending=False,excluded=category=='infra_error',tests_passed=tests,tamper=tamper,category=category,
            solved_by_tests=tests is True and tamper is False and category!='infra_error',native_grade_record=item['grade_record'],
            execution_host=item['execution_host'],grading_host=item['grading_host'],grading_host_changed=item['execution_host']!=item['grading_host'])
        old['flags']=[f for f in old.get('flags',[]) if not f.startswith('Native tests pending')]
        if old!=new:raise ValueError('Completed native report changed execution measurements or unrelated fields')
    expected['pending_native_grades']=sum(bool(r.get('native_grade_pending')) for r in expected['rows'])
    expected['complete']=expected['pending_native_grades']==0 and expected['pending_mac_grades']==0
    if expected!=current:raise ValueError('Completed native report metadata changed')


def recheckpoint(root,previous_pending=None):
    scope=root/'results/session4';spec=json.loads((scope/'resume.json').read_text())
    # Every other byte binding remains strict; this is an explicit state advance.
    for name,digest in spec['files'].items():
        if name=='pending_native.json':continue
        if Path(name).name!=name or sha(scope/name)!=digest:raise ValueError('Resume checkpoint changed: '+name)
    raw=(scope/'pending_native.json').read_text()
    if hashlib.sha256(raw.encode()).hexdigest()==spec['files']['pending_native.json']:
        verify_checkpoint(root);return
    baseline=Path(previous_pending).read_text() if previous_pending else spec.get('pending_native_snapshot')
    if baseline is None or hashlib.sha256(baseline.encode()).hexdigest()!=spec['files']['pending_native.json']:
        raise ValueError('Re-checkpoint needs the exact previously bound pending_native.json')
    previous,current=json.loads(baseline),json.loads(raw);changed=completed_transition(previous,current)
    if 'resume_c16.json' in spec['files']:
        before=json.loads((scope/'resume_c16.json').read_text())
    else:
        with tarfile.open(scope/'resume_data.tar.gz','r:gz') as t:before=json.load(t.extractfile('data/rocm-recipes-006/live/c16/runs.json'))
    report_path=root/'results/atlas/scored/live/c16/runs.json';report=json.loads(report_path.read_text())
    completed_report(before,report,current)
    (scope/'resume_c16.json').write_bytes(report_path.read_bytes())
    spec.update(version=2,pending_native_snapshot=raw)
    spec['files']['pending_native.json']=sha(scope/'pending_native.json')
    spec['files']['resume_c16.json']=sha(scope/'resume_c16.json')
    temporary=scope/'resume.json.tmp';save(temporary,spec);temporary.replace(scope/'resume.json')
    print('Re-checkpointed completed native grades: '+', '.join(changed))


def restore(root,atlas):
    scope=root/'results/session4';manifest=scope/'resume.json'
    if not manifest.exists():return
    spec=verify_checkpoint(root)
    if (atlas/'data').exists():raise ValueError('Resume needs fresh ATLAS data')
    with tarfile.open(scope/'resume_data.tar.gz','r:gz') as t:
        members=t.getmembers();links={m.name.rstrip('/') for m in members if m.issym()}
        for m in members:
            p=Path(m.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='data' or not (m.isdir() or m.isfile() or m.issym()):raise ValueError('Unsafe checkpoint member')
            if any(str(a) in links for a in p.parents):raise ValueError('Checkpoint member traverses symlink')
        # Symlinks are retained as evidence, never followed when extracting files.
        for m in members:
            target=atlas/m.name
            if m.isdir():target.mkdir(parents=True,exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as f:shutil.copyfileobj(t.extractfile(m),f)
                target.chmod(m.mode&0o777)
        for m in members:
            if m.issym():(atlas/m.name).symlink_to(m.linkname)
        for m in reversed(members):
            if m.isdir():(atlas/m.name).chmod(m.mode&0o777)
    if 'resume_c16.json' in spec['files']:
        path=atlas/'data/rocm-recipes-006/live/c16/runs.json'
        report=json.loads((scope/'resume_c16.json').read_text())
        completed_report(json.loads(path.read_text()),report,json.loads((scope/'pending_native.json').read_text()))
        save(path,report);save(root/'results/atlas/scored/live/c16/runs.json',report)
    print('Restored session-4 execution checkpoint; c16 complete, next c8; '+('completed native grades retained.' if 'resume_c16.json' in spec['files'] else 'native grade required after check-host.'))


def offline(root,atlas):
    scope=root/'results/session4';source=scope/'atlas/data';out=scope/'reh005'
    out.mkdir(parents=True,exist_ok=True)
    oldpath=root/'results/atlas/scored/live/c16/runs.json'
    if not (out/'live_c16_before.json').exists():shutil.copyfile(oldpath,out/'live_c16_before.json')
    if not (out/'progress_before.json').exists():shutil.copyfile(scope/'progress.json',out/'progress_before.json')
    counts=root/'results/grading/counts/c16.json'
    if counts.exists() and not (out/'counts_before.json').exists():shutil.copyfile(counts,out/'counts_before.json')
    before=json.loads((out/'live_c16_before.json').read_text())
    with tempfile.TemporaryDirectory() as tmp:
        dbpath=Path(tmp)/'atlas.db';shutil.copyfile(source/'rocm-recipes-006/atlas.db',dbpath)
        db=sqlite3.connect(dbpath);db.row_factory=sqlite3.Row
        row=dict(db.execute('select * from runs where run_id=?',(RUN,)).fetchone())
        assert not db.execute('select * from grades where run_id=?',(RUN,)).fetchone()
        expected=[]
        for name in ('c16','c16-retry1','c16-retry2'):
            m=json.loads((source/f'rocm-recipes-006-session4/{name}.json').read_text())
            expected.extend(f"{r['task']}__{r['config']}__a{r['attempt']}" for r in m['runs'])
        rows={r['run_id']:dict(r) for r in db.execute('select * from runs') if r['run_id'] in expected};db.close()
    assert len(expected)==32 and set(expected)==set(rows) and all(r['state']=='finished' for r in rows.values())
    extract=subprocess.run(['node',str(root/'scripts/session4_retained_006.ts'),'extract',str(source.resolve()),str(atlas)],cwd=source.parent,input=json.dumps(row),capture_output=True,text=True,check=True)
    captured=json.loads(extract.stdout);save(out/'retry2_evidence.json',captured)
    report=copy.deepcopy(before)
    # Bind the existing audited Mac result without changing native verdicts.
    for r in report['rows']:
        if not r.get('grading_pending'):continue
        pending=root/'results/grading/pending'/r['run_id'];returned=root/'results/grading/returned'/r['run_id']
        raw=(pending/'request.json').read_bytes();request=json.loads(raw);response=json.loads((returned/'response.json').read_text());audit=json.loads((returned/'audit.json').read_text())
        assert response['request_sha256']==hashlib.sha256(raw).hexdigest() and response['run_id']==r['run_id']
        assert response['atlas_commit']==request['atlas_commit']==before['atlas_commit'] and request['run_id']==r['run_id']
        claim=response['claim'];assert claim['audited'] and claim['source']=='llm_fallback' and audit['accepted'] and audit['expected']==audit['reported']==claim['claim'] and audit['reviewer'] and audit['reason']
        assert sha(pending/'native-tests/tests.json')==request['native_tests_sha256']
        assert r['tests_passed']==request['record']['tests']['testsPassed'] and r['tamper']==request['record']['protection']['tamper']
        r.update(grading_pending=False,claim=claim['claim'],claim_source=claim['source'],category=response['category'],mac_grade=dict(request_sha256=response['request_sha256'],response=str(returned/'response.json')))
    extra=copy.deepcopy(next(r for r in before['rows'] if r['run_id']==row['retry_of']))
    limits=json.loads(row['limits_json']);totals=limits['totals']
    extra.update(captured['metrics']);extra.update(run_id=RUN,attempt=row['attempt'],retry_of=row['retry_of'],started_at=row['started_at'],ended_at=row['ended_at'],wall_s=row['wall_s'],end_reason=row['end_reason'],
        evidence_available=True,evidence_path=row['trace_path'],native_grade_pending=True,excluded=True,grading_pending=False,grading_key=RUN,tests_passed=None,tamper=None,solved_by_tests=None,
        category='native_grade_pending',claim=None,claim_source=None,mac_grade=None,missing_status=False,flags=['Native tests pending on next checked amd64 host; excluded from solved and failed counts'],
        execution_host=captured['execution_host'],token_source='proxy',cost_usd=row['cost_usd'],refusal_count=None,reasoning_observed=None,tool_parse_error=None,cache_reporting_verified=None,
        proxy_request_count=None,cached_requests_after_first=[],token_accounting=totals['tokenAccounting'],soft_token_limit=totals['softTokenLimit'],token_overshoot=totals['tokenOvershoot'],
        tokens_uncached_in=totals['tokensUncachedIn'],tokens_cumulative=totals['tokensCumulative'],tokens_counted=totals['tokensCounted'],cap_at=limits['cap']['at'],agent_stopped_at=limits['agentStoppedAt'],cap_stop_latency_ms=limits['stopLatencyMs'])
    report['rows'].append(extra);report.update(complete=False,execution_complete=True,pending_mac_grades=0,pending_native_grades=1,offline_recovered=True)
    assert {r['run_id'] for r in report['rows']}==set(expected)
    for field in ('tokens_in','tokens_out','tokens_cached','inference_s'):
        assert extra[field]==row[field],(field,extra[field],row[field])
    comparison={}
    for field in ('wall_s','tokens_in','tokens_out','tokens_cached','inference_s'):
        measured=[r[field] for r in report['rows']];actual=[rows[r['run_id']][field] for r in report['rows']]
        # Existing live evidence deliberately nulls unavailable reconciled usage.
        pairs=[(a,b) for a,b in zip(measured,actual) if a is not None]
        assert all(b is not None and abs(a-b)<1e-7 for a,b in pairs),field
        comparison[field]=dict(export_known_sum=sum(a for a,b in pairs),db_same_rows_sum=sum(b for a,b in pairs),known_rows=len(pairs),null_rows=sum(a is None for a in measured),db_all_known_sum=sum(v for v in actual if v is not None),db_null_rows=sum(v is None for v in actual))
    save(out/'totals_check.json',dict(attempts=32,base=30,retries=2,fields=comparison,original_live_rows_preserved=31,native_grade_pending=RUN))
    grade=next((source/'grading').glob('*/c09__qwen38-27b-mi300x__a1161/*/grade.json'))
    original=json.loads(grade.read_text());save(out/'diagnosis.json',dict(artifact=str(grade),remote_artifact=original['directory']+'/grade.json',real_path=str(grade.resolve()),inside_data=grade.resolve().is_relative_to(source.resolve()),symlink=grade.is_symlink(),regular_file=grade.is_file(),auth_store=False,actual_bytes=grade.stat().st_size,maximum_bytes=32*1024*1024,failed_condition='size > max',source_sha256=sha(grade)))
    pending=dict(runs=[dict(row=row,proof=captured['proof'],status='pending',execution_host=captured['execution_host'])])
    save(scope/'pending_native.json',pending)
    shutil.copyfile(source/'rocm-recipes-006-native-session4/image-map.json',scope/'execution-image-map.json')
    progress=json.loads((out/'progress_before.json').read_text());began=progress['active']['started_at']
    ended=max(r['ended_at'] for r in rows.values());observed=(datetime.fromisoformat(ended.replace('Z','+00:00'))-datetime.fromisoformat(began)).total_seconds()
    progress=dict(completed=[dict(level='c16',observed_wall_s=observed,execution_complete=True,attempts=32,pending_native_grades=1,source='offline REH-005 export',decision=dict(remaining=['c8','c4','c1'],reason='Previous session ended before guard; next session starts fresh lifecycle. Apply unchanged per-level guard after c8, c4 and c1.'))],remaining=['c8','c4','c1'],active=None)
    save(scope/'progress.json',progress);save(oldpath,report)
    save(out/'runs.json',report)
    save(counts,dict(level='c16',stage='c16',missing_status_runs=sum(bool(r.get('missing_status')) for r in report['rows']),pending_mac_grades=0,pending_native_grades=1,run_ids=[],native_run_ids=[RUN]))
    samples=[str(p) for p in (root/'results/raw').glob('c16*/samples.jsonl')]
    subprocess.run(['python3',str(root/'scripts/summarize_006.py'),str(out/'runs.json'),'--live','--output-dir',str(out/'live'),'--samples',*samples],check=True)
    subprocess.run(['python3',str(root/'scripts/summarize_006.py'),str(out/'runs.json'),'--live','--output-dir',str(root/'results/live'),'--samples',*samples],check=True)
    # A fresh host gets prior execution/grade evidence, not the previous host's
    # native build outputs. Preserve source data; normalize only the new copy.
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint=Path(tmp);data=checkpoint/'data'
        shutil.copytree(source,data,symlinks=True,ignore=lambda p,n:[x for x in n if (Path(p)==source and x=='rocm-recipes-006-native-session4') or (Path(p)==source/'rocm-recipes-006-session4' and x=='session4.json')])
        local_grade=data/grade.relative_to(source)
        program='import {readFile} from "node:fs/promises";import{compactGrade}from '+json.dumps(str(root/'scripts/export_support_006.ts'))+';console.log(JSON.stringify(await compactGrade(JSON.parse(await readFile(process.argv[1],"utf8")),process.argv[2],process.argv[3])));'
        result=subprocess.run(['node','--input-type=module','-e',program,str(local_grade),str(atlas),str(local_grade.parent)],cwd=checkpoint,capture_output=True,text=True,check=True)
        save(out/'compaction.json',json.loads(result.stdout));save(data/'rocm-recipes-006/live/c16/runs.json',report)
        with tarfile.open(scope/'resume_data.tar.gz','w:gz',compresslevel=1) as t:t.add(data,arcname='data')
    files=['resume_data.tar.gz','progress.json','pending_native.json','execution-image-map.json']
    save(scope/'resume.json',dict(version=1,execution_complete=['c16'],next_level='c8',files={name:sha(scope/name) for name in files}))
    print('Offline c16: 32 attempts; native grade pending, c16 execution complete; resume c8 -> c4 -> c1.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['offline','restore','checkpoint']);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--atlas',type=Path);p.add_argument('--previous-pending',type=Path);a=p.parse_args()
    if a.mode=='checkpoint':recheckpoint(a.root.resolve(),a.previous_pending)
    else:
        if a.atlas is None:p.error('--atlas is required for offline/restore')
        (offline if a.mode=='offline' else restore)(a.root.resolve(),a.atlas.resolve())
