#!/usr/bin/env python3
"""Finalize synced live results on the Mac after all claim audits, without a droplet."""
import argparse
import hashlib
import json
from pathlib import Path
from summarize_006 import PIN, summarize, write_csv, write_matched


def finalize(paths, root, samples=(), rehearsal=False, output_dir=None):
    results = root / ('results/rehearsal' if rehearsal else 'results')
    native_queue=results/'session4/pending_native.json'
    if not rehearsal and native_queue.exists() and any(r.get('status')!='complete' for r in json.loads(native_queue.read_text())['runs']):
        raise ValueError('Final export blocked by pending native grades')
    if output_dir is not None:
        output_dir = Path(output_dir)
        if not output_dir.is_absolute():
            output_dir = root / output_dir
        output_dir = output_dir.resolve()
        if not rehearsal:
            raise ValueError('Custom output directory is rehearsal-only')
        try:
            output_dir.relative_to(results.resolve())
        except ValueError as error:
            raise ValueError('Rehearsal output directory must stay under results/rehearsal') from error
    reports = []
    for path in paths:
        report = json.loads(path.read_text())
        if bool(report.get('rehearsal')) != rehearsal:
            raise ValueError('Finalization mode mismatch')
        if report.get('atlas_commit') != PIN:
            raise ValueError('Live export pin differs from the approved ATLAS pin')
        if report.get('pending_native_grades') or any(r.get('native_grade_pending') for r in report['rows']):
            raise ValueError('Final export blocked by pending native grades')
        if report.get('execution_complete') is not True:
            raise ValueError('Execution is not complete: ' + str(path))
        for row in report['rows']:
            if not row.get('grading_pending'):
                continue
            run = row['run_id']
            key = row.get('grading_key', run)
            if Path(key).name != key or key in ('.','..'):
                raise ValueError('Unsafe grading key')
            pending = results / 'grading/pending' / key
            returned = results / 'grading/returned' / key
            raw = (pending / 'request.json').read_bytes()
            request = json.loads(raw)
            response = json.loads((returned / 'response.json').read_text())
            audit = json.loads((returned / 'audit.json').read_text())
            claim = response['claim']
            if (response['request_sha256'] != hashlib.sha256(raw).hexdigest()
                    or response['run_id'] != run or response['atlas_commit'] != PIN
                    or request['run_id'] != run or request['atlas_commit'] != PIN
                    or claim.get('audited') is not True or claim.get('source') != 'llm_fallback'
                    or audit.get('accepted') is not True or audit.get('expected') != claim['claim']
                    or audit.get('reported') != claim['claim'] or not audit.get('reviewer') or not audit.get('reason')):
                raise ValueError('Unbound or unaudited Mac grade: ' + run)
            if hashlib.sha256((pending / 'native-tests/tests.json').read_bytes()).hexdigest() != request['native_tests_sha256']:
                raise ValueError('Native test evidence changed: ' + run)
            record = request['record']
            if row['tests_passed'] != record['tests']['testsPassed'] or row['tamper'] != record['protection']['tamper']:
                raise ValueError('Native verdict differs from live export: ' + run)
            row.update(grading_pending=False, claim=claim['claim'], claim_source=claim['source'],
                       category=response['category'], mac_grade={'request_sha256': response['request_sha256'], 'response': str(returned / 'response.json')})
        report.update(complete=True, pending_mac_grades=0)
        reports.append(report)
    # Validate every input/audit before creating any final output.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        temporary = []
        for i, report in enumerate(reports):
            p = Path(tmp) / f'{i}.json'; p.write_text(json.dumps(report)); temporary.append(p)
        summarize(temporary, samples, allow_fixtures=rehearsal, strict=True)
    final_paths = []
    for report in reports:
        level = report['rows'][0]['level']
        final_root = output_dir if output_dir is not None else results / ('atlas/main/final' if rehearsal else 'atlas/scored/final')
        target = final_root / level / 'runs.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + '\n')
        final_paths.append(target)
    summary, rows = summarize(final_paths, samples, allow_fixtures=rehearsal, strict=True)
    csv_root = output_dir if output_dir is not None else results
    csv_root.mkdir(parents=True, exist_ok=True)
    write_csv(csv_root / 'summary.csv', summary)
    write_csv(csv_root / 'runs.csv', rows)
    write_matched(csv_root, summary, rows)
    return len(rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('exports', nargs='+', type=Path)
    p.add_argument('--study-root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--rehearsal', action='store_true')
    p.add_argument('--samples', nargs='*', type=Path, default=[])
    p.add_argument('--output-dir', type=Path, help='Optional output directory under results/rehearsal (rehearsal only)')
    a = p.parse_args()
    try:
        print(f'Finalized {finalize(a.exports, a.study_root, a.samples, a.rehearsal, a.output_dir)} runs')
    except (ValueError, OSError, KeyError) as error:
        p.exit(1, f'Final export blocked: {error}\n')
