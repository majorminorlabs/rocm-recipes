"""R5/R6 regressions using proxy fixtures and stubbed server commands only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prefix_sched as client
from summarize_006 import PIN


class ReportingTests(unittest.TestCase):
    def test_runtime_flags_and_identical_kx_policies(self):
        # Exercise the shared launch function, stopping before provenance/inference.
        source = (ROOT / 'scripts/atlas_remote.sh').read_text()
        serve = source[source.index('stop_server() {'):source.index('\nqueue() {')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'scripts').mkdir(); (root / 'logs').mkdir()
            commands = {
                root / 'scripts/stop_engine.sh': 'exit 0',
                root / 'scripts/serve_engine.sh': 'printf "%s\\n" "$@" > "$CALL_LOG"; exit 42',
                root / 'docker': 'exit 0',
            }
            for path, body in commands.items():
                path.write_text('#!/bin/sh\n' + body + '\n'); path.chmod(0o755)
            calls = {}
            for engine, policy in [('vllm', 'lpm'), ('sglang', 'lpm'), ('sglang', 'fcfs')]:
                env = dict(os.environ, ROOT_DIR=str(root), LOG_DIR=str(root/'logs'), REHEARSAL='0', MODEL='fake', VLLM_IMAGE='fake', SGLANG_IMAGE='fake',
                           CALL_LOG=str(root / 'call'), ENGINE=engine, POLICY=policy, PATH=tmp + ':' + os.environ['PATH'])
                r = subprocess.run(['bash'], input=serve + '\nserve "$ENGINE" "$POLICY"\n', env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 42, r.stderr)
                calls[engine, policy] = (root / 'call').read_text().splitlines()
            self.assertEqual(calls['vllm', 'lpm'].count('--enable-prompt-tokens-details'), 1)
            for policy in ('lpm', 'fcfs'):
                self.assertEqual(calls['sglang', policy].count('--enable-cache-report'), 1)
            lpm = calls['sglang', 'lpm']; fcfs = calls['sglang', 'fcfs']
            index = lpm.index('--schedule-policy') + 1
            self.assertEqual(lpm[index], 'lpm'); self.assertEqual(fcfs[index], 'fcfs')
            fcfs[index] = 'lpm'; self.assertEqual(fcfs, lpm)

    def test_smoke_requires_proxy_cache_hit_after_first_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scripts = root / 'study/scripts'; scripts.mkdir(parents=True)
            atlas = root / 'atlas'; atlas.mkdir(); bin = root / 'bin'; bin.mkdir()
            for name in ('atlas_export_006.ts', 'export_support_006.ts', 'atlas_mac_grade_006.ts'):
                shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
            git = bin / 'git'; git.write_text('#!/bin/sh\necho ' + PIN + '\n'); git.chmod(0o755)
            modules = {
                'runner/manifest.ts': "export const loadManifest=async()=>({manifest:{id:'vllm-smoke',study:{level:'c1',dryRun:true}},runs:[{runId:'smoke'}]});",
                'runner/store.ts': "export class Store{db={prepare:()=>({get:()=>({status:'complete'})})};row(){return {state:'finished',end_reason:'completed',backend:'local',harness:'opencode',trace_path:'fake'};}close(){}}",
                'grading/claim.ts': "export const parseStatus=()=> 'done';",
                'grading/evidence.ts': "export const artifactText=async()=> '{}';export const readEvidence=async()=>({finalMessage:'STATUS: DONE'});",
                'grading/service.ts': "import{readFile}from'node:fs/promises';export const gradeRun=async()=>JSON.parse(await readFile('grade.json','utf8'));",
            }
            for path, body in modules.items():
                p = atlas / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
            env = dict(os.environ, PATH=str(bin) + ':' + os.environ['PATH'])
            cases = [
                ('missing', [None, None], False),
                ('zero', [0, 0], False),
                ('first-only', [100, 0], False),
                ('one-request', [100], False),
                ('later-hit', [0, 100], True),
                ('string-not-count', [0, '100'], False),
                ('not-proxy', [0, 100], False),
            ]
            for label, counts, passes in cases:
                with self.subTest(label=label):
                    requests = [dict(event='request', request_id=str(i)) for i in range(len(counts))]
                    # Reverse completion order to ensure "first" means first request.
                    responses = [dict(event='response', request_id=str(i), tokens_cached=n,
                                      token_source='self_report' if label == 'not-proxy' else 'proxy',
                                      response=dict(choices=[dict(message=dict(reasoning_content='thinking'))]))
                                 for i, n in reversed(list(enumerate(counts)))]
                    grade = dict(runId='smoke', status='complete', executionRow=dict(task_id='c13', limits_json='null'),
                                 evidence=dict(raw=requests + responses, tokens=dict(input=100, output=10, cached=100),
                                               toolCalls=[dict(name='tool')], tokenSource='proxy', inferenceS=1),
                                 tests=dict(testsPassed=True), protection=dict(tamper=False), category='solved',
                                 claim=dict(claim='done'), cost=dict(costUsd=0), flags=[])
                    (atlas / 'grade.json').write_text(json.dumps(grade))
                    db = atlas / f'data/{label}.db'
                    r = subprocess.run(['node', str(scripts / 'atlas_export_006.ts'), 'manifest', str(db)],
                                       cwd=atlas, env=env, capture_output=True, text=True)
                    self.assertEqual(r.returncode == 0, passes, r.stderr)
                    if not passes:
                        self.assertIn('no nonzero proxy cached tokens after the first request', r.stderr)
                    report = json.loads((db.parent / f'live/{label}/runs.json').read_text())
                    self.assertEqual(report['rows'][0]['cache_reporting_verified'], passes)
                    self.assertEqual(report['rows'][0]['proxy_request_count'], len(counts))


class SuccessfulTTFTTests(unittest.TestCase):
    def test_failed_and_partially_streamed_rows_do_not_affect_percentiles(self):
        def row(group, status, ttft):
            return dict(group=group, status=status, ttft_s=ttft, cached_tokens=None, prompt_tokens=None, output_tokens=None)
        rows = [row('G1', 'ok', 1), row('G1', 'ok', 3), row('G1', 'error', None), row('G1', 'error', 99),
                row('G2', 'error', 10), row('G2', 'error', None)]
        summary = client.summarize(rows, 2, [dict(name=None, value=None)] * 2)
        g1, g2, empty = [summary['groups'][g] for g in ('G1', 'G2', 'G3')]
        self.assertEqual((g1['requests'], g1['ok'], g1['failed']), (4, 2, 2))
        self.assertEqual(g1['ttft_p50_s'], 2); self.assertAlmostEqual(g1['ttft_p95_s'], 2.9)
        self.assertEqual(g2['failed'], 2); self.assertEqual(g2['ok'], 0)
        for group in (g2, empty):
            self.assertIsNone(group['ttft_p50_s']); self.assertIsNone(group['ttft_p95_s'])
        self.assertEqual(empty['failed'], 0)


if __name__ == '__main__':
    unittest.main()
