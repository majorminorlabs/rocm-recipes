"""Offline regression checks, including the retained P0.5 and amended-D2 exports."""
import copy
import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('summary', ROOT / 'scripts/summarize_006.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class SummaryTests(unittest.TestCase):
    def check_export(self, name, attempts):
        path = ROOT / f'inputs/atlas-dry-{name}/runs.json'
        original = json.loads(path.read_text())
        levels, rows = summary.summarize([path], allow_fixtures=True)
        self.assertEqual(len(rows), attempts)
        for actual, expected in zip(levels, original['levels']):
            for field in ('level', 'runs', 'solved', 'tokens_in', 'tokens_out'):
                self.assertEqual(actual[field], expected[field])
            for field in ('success_rate', 'level_wall_s', 'successful_tasks_per_hour', 'wall_p50_s', 'wall_p95_s'):
                self.assertAlmostEqual(actual[field], expected[field], places=6)
            self.assertTrue(actual['fixture'])
            self.assertFalse(actual['scored'])
            self.assertIsNone(actual['level_gpu_hours'])
            self.assertIsNone(actual['billable_gpu_hours'])
            self.assertIsNone(actual['ttft_p50_s'])
            self.assertIsNone(actual['peak_vram_mb'])
        with self.assertRaisesRegex(ValueError, 'allow-fixtures'):
            summary.summarize([path])
        return levels, rows

    def test_p05_and_excluded_infra(self):
        levels, rows = self.check_export('p05', 10)
        self.assertEqual([s['infra_attempts'] for s in levels], [2, 2])
        self.assertEqual([s['infra_reruns'] for s in levels], [2, 2])
        self.assertEqual(sum(r['included'] for r in rows), 6)
        self.assertTrue(all(s['timing_contains_repair_gap'] for s in levels))
        self.assertTrue(all(s['all_attempts_tokens_in'] is None for s in levels))

    def test_p08_caps_and_cache(self):
        levels, rows = self.check_export('p08', 6)
        self.assertEqual([s['failure_turn_cap'] for s in levels], [2, 0])
        self.assertEqual([s['failure_wrong_answer'] for s in levels], [0, 2])
        for s in levels:
            self.assertEqual(s['tokens_counted'], s['tokens_in'] - s['tokens_cached'] + s['tokens_out'])
            self.assertEqual(s['token_overshoot'], 0)
        for r in rows:
            if r['cap_at']:
                self.assertEqual(r['ended_at'], r['cap_at'])
                self.assertLess(r['cap_stop_latency_ms'], 2000)

    def test_csv_same_scored_metrics(self):
        base = ROOT / 'inputs/atlas-dry-p08'
        a, _ = summary.summarize([base / 'runs.json'], allow_fixtures=True)
        b, _ = summary.summarize([base / 'runs.csv'], allow_fixtures=True)
        self.assertEqual(a, b)

    def test_duplicate_exports_rejected(self):
        p = ROOT / 'inputs/atlas-dry-p08/runs.json'
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            summary.summarize([p, p], allow_fixtures=True)

    def test_gpu_overlap_samples_and_missing_usage(self):
        original = json.loads((ROOT / 'inputs/atlas-dry-p08/runs.json').read_text())
        # Simultaneous synthetic runs ensure billing uses elapsed window, never sum(wall).
        source = original['rows'][0]
        rows = []
        for i, category in enumerate(('solved', 'token_cap')):
            r = dict(source, run_id=f'synthetic-{i}', level='c16', config='qwen38-27b-mi300x',
                model='Qwen/Qwen3.8-27B', fixture=False, scored=True, category=category,
                started_at='2026-10-15T00:00:00Z', ended_at='2026-10-15T01:00:00Z',
                end_reason='completed' if i == 0 else 'token_cap', wall_s=3600,
                tokens_in=500000, tokens_out=12000, tokens_cached=100000,
                tokens_uncached_in=400000, tokens_counted=412000, tokens_cumulative=512000,
                token_overshoot=12000, flags=[], tests_passed=i == 0, tamper=False)
            rows.append(r)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'export.json'
            p.write_text(json.dumps(dict(complete=True, rows=rows)))
            samples = Path(tmp) / 'samples.jsonl'
            samples.write_text('\n'.join(json.dumps(s) for s in [
                dict(ts=summary.timestamp('2026-10-15T00:30:00Z'), peak_vram_mb=100, kv_usage=.5, host_cpu_percent=93, host_ram_used_mb=200),
                dict(ts=summary.timestamp('2026-10-15T02:00:00Z'), peak_vram_mb=999, kv_usage=.9)]))
            levels, _ = summary.summarize([p], [samples])
            s = levels[0]
            self.assertEqual(s['level_gpu_hours'], 1)
            self.assertEqual(s['wall_s'], 7200)
            self.assertEqual(s['level_gpu_cost_usd'], 1.99)
            self.assertEqual(s['successful_tasks_per_hour'], 1)
            self.assertEqual(s['tokens_counted'], 824000)
            self.assertEqual(s['token_overshoot'], 24000)
            self.assertEqual(s['peak_vram_mb'], 100)
            self.assertEqual(s['peak_host_cpu_percent'], 93)
            self.assertEqual(s['sample_count'], 1)
            rows[1]['tokens_in'] = None
            p.write_text(json.dumps(dict(rows=rows)))
            s = summary.summarize([p])[0][0]
            self.assertIsNone(s['tokens_in'])
            rows[1]['tokens_in'] = 2  # invalid exact cached usage
            p.write_text(json.dumps(dict(rows=rows)))
            with self.assertRaisesRegex(ValueError, 'Cached input'):
                summary.summarize([p])

    def test_fixture_cli_cannot_write_scored_results(self):
        r = subprocess.run(['python3', str(ROOT / 'scripts/summarize_006.py'),
            str(ROOT / 'inputs/atlas-dry-p08/runs.json'), '--allow-fixtures'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('separate', r.stderr)

    def test_deterministic_csvs(self):
        path = ROOT / 'inputs/atlas-dry-p08/runs.json'
        a, b = summary.summarize([path], allow_fixtures=True)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'out.csv'
            summary.write_csv(p, a); first = p.read_bytes()
            summary.write_csv(p, a); self.assertEqual(first, p.read_bytes())
            summary.write_csv(p, b); first = p.read_bytes()
            summary.write_csv(p, b); self.assertEqual(first, p.read_bytes())


class WrapperTests(unittest.TestCase):
    def test_dry_runs_never_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'invoked'
            # Any accidental cloud, remote or Docker dispatch fails and leaves evidence.
            for cmd in ('ssh', 'scp', 'docker', 'doctl', 'tmux', 'curl', 'rsync', 'apt-get', 'useradd', 'usermod'):
                p = Path(tmp) / cmd
                p.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 98\n'); p.chmod(0o755)
            env = dict(os.environ, PATH=tmp + ':' + os.environ['PATH'])
            for args in (['setup'], ['probe'], ['serve', 'vllm'], ['serve', 'sglang'], ['run', 'c16'], ['status'], ['sync-grading'], ['phase3b']):
                r = subprocess.run(['bash', str(ROOT / 'scripts/atlas_remote.sh'), '--dry-run', *args],
                    env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(summary.PIN, r.stdout)
                self.assertIn('http://localhost:8000/v1', r.stdout)
                if args[0] in ('probe', 'serve'):
                    self.assertIn('--tool-call-parser qwen3_coder', r.stdout)
                    self.assertIn('--reasoning-parser qwen3', r.stdout)
                    self.assertIn('131072', r.stdout)
                    self.assertNotIn('--disable-radix-cache', r.stdout)
                    self.assertNotIn('--no-enable-prefix-caching', r.stdout)
            self.assertFalse(marker.exists())

    def test_engine_choice_rule(self):
        # Exercise the actual chooser offline, with a fake Git identity and measured reports.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); (base / 'bin').mkdir()
            git = base / 'bin/git';git.write_text('#!/bin/sh\necho ' + summary.PIN + '\n');git.chmod(0o755)
            for engine, duration, outputs in [('vllm', 60, 300), ('sglang', 120, 300)]:
                for stage in ('smoke', 'c8'):
                    out = base / f'data/rocm-recipes-006-probe/live/{engine}-{stage}'
                    out.mkdir(parents=True)
                    row = dict(category='solved', solved_by_tests=True, grading_pending=True, claim=None, tool_calls=1, reasoning_observed=True, tool_parse_error=False,cache_reporting_verified=True,
                               started_at='2026-10-15T00:00:00Z', ended_at=f'2026-10-15T00:0{duration // 60}:00Z',tokens_out=outputs)
                    tasks=['c39','c13','c28','c29','c40','c43','c45','c18'] if stage=='c8' else ['c13']
                    (out / 'runs.json').write_text(json.dumps(dict(rows=[dict(row,task=task) for task in tasks])))
            out = base / 'choice.md'
            r = subprocess.run(['node', str(ROOT / 'scripts/atlas_export_006.ts'), '--choose', str(out)],
                cwd=base, env=dict(os.environ, PATH=str(base / 'bin') + ':' + os.environ['PATH']),capture_output=True,text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            choice=json.loads(out.with_suffix('.json').read_text())
            self.assertEqual(choice['engine'], 'vllm')
            self.assertTrue(all(c['pending_mac_grades']==8 for c in choice['candidates']))
            self.assertIn('Reporting-only flags', out.read_text())
            self.assertIn('--enable-prompt-tokens-details', out.read_text())
            self.assertIn('--enable-cache-report', out.read_text())
            # The chooser also rejects stale/failed smoke evidence if invoked directly.
            for engine in ('vllm', 'sglang'):
                smoke=base/f'data/rocm-recipes-006-probe/live/{engine}-smoke/runs.json'
                data=json.loads(smoke.read_text());data['rows'][0]['cache_reporting_verified']=False
                smoke.write_text(json.dumps(data))
                r=subprocess.run(['node', str(ROOT/'scripts/atlas_export_006.ts'), '--choose', str(out)],
                    cwd=base,env=dict(os.environ,PATH=str(base/'bin')+':'+os.environ['PATH']),capture_output=True,text=True)
                if engine=='vllm':
                    self.assertEqual(r.returncode,0,r.stderr)
                    self.assertEqual(json.loads(out.with_suffix('.json').read_text())['engine'],'sglang')
                else:
                    self.assertNotEqual(r.returncode,0)
                    self.assertIn('Neither engine passes probe',r.stderr)


class GateTests(unittest.TestCase):
    def test_review_gate_and_scaling(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('gate', ROOT / 'scripts/atlas_gate_006.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('logs', 'notes', 'results'):
                (root / folder).mkdir()
            state = dict(steps={f'P0.{i}': dict(status='DONE') for i in range(3, 9)})
            (root / 'STATE.json').write_text(json.dumps(state))
            (root / 'notes/engine_choice.json').write_text(json.dumps(dict(engine='vllm')))
            (root / 'logs/current_server.json').write_text(json.dumps(dict(engine='vllm', hf_repo='Qwen/Qwen3.8-27B', max_model_len=131072, weights_precision='bf16')))
            with (root / 'results/summary.csv').open('w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['level','scored','runs','level_gpu_hours','successful_tasks_per_hour','success_rate'])
                w.writeheader()
                for c, throughput in [(1,10),(4,20),(8,30),(16,34)]:
                    w.writerow(dict(level=f'c{c}',scored='true',runs=60 if c==16 else 30,level_gpu_hours=1,successful_tasks_per_hour=throughput,success_rate=.8))
            now = datetime.now(timezone.utc)
            env = dict(CREATED_AT=(now-timedelta(hours=2)).isoformat(), HARD_DEADLINE=(now+timedelta(hours=7)).isoformat(), SESSION_CAP_HOURS='9')
            with patch.dict(os.environ, env):
                module.gate(root, 'c1');module.gate(root, 'c4');module.gate(root, 'c32')
                text=(root / 'results/summary.csv').read_text().replace('34,0.8','32,0.8')
                (root / 'results/summary.csv').write_text(text)
                with self.assertRaisesRegex(ValueError, 'c32'):
                    module.gate(root, 'c32')
                state['steps']['P0.8']['status']='TODO'
                (root / 'STATE.json').write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, 'P0.8'):
                    module.gate(root, 'c1')

    def test_engine_probe_settings_match_005(self):
        r = subprocess.run(['bash', str(ROOT / 'scripts/atlas_remote.sh'), '--dry-run','probe'],capture_output=True,text=True,check=True)
        self.assertIn('VLLM_ROCM_USE_AITER=1', r.stdout)
        self.assertIn('ROCM_AITER_UNIFIED_ATTN', r.stdout)
        self.assertIn('--max-num-batched-tokens 16384', r.stdout)
        self.assertIn('--schedule-policy lpm', r.stdout)
        self.assertIn('--enable-prompt-tokens-details', r.stdout)
        self.assertIn('--enable-cache-report', r.stdout)
        self.assertIn('nonzero proxy cached tokens after the first request', r.stdout)
        self.assertLess(r.stdout.index('serve vllm'),r.stdout.index('serve sglang'))


if __name__ == '__main__':
    unittest.main()
