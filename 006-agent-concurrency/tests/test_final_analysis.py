"""Final score semantics, measured-only accounting and exact statistical tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from analyze_final_006 import wilson, fisher_exact, usage, exact_window, audit_inventory
from summarize_006 import summarize, write_matched
from finalize_006 import finalize


class FinalAnalysisTests(unittest.TestCase):
    @unittest.skipIf(not (ROOT / 'results/atlas/scored/live/c16/runs.json').is_file(), 'requires archived live run records, not distributed')
    def test_strict_frozen_counts_on_all_three_real_levels(self):
        paths=[ROOT/f'results/atlas/scored/live/{l}/runs.json' for l in ('c16','c8','c4')]
        levels,rows=summarize(paths,allow_pending=True,strict=True)
        lookup={s['level']:s for s in levels}
        self.assertEqual({l:(s['runs'],s['solved']) for l,s in lookup.items()},{'c16':(29,3),'c8':(29,7),'c4':(29,6)})
        timeout=next(r for r in rows if r['run_id']=='c24__qwen38-27b-mi300x__a5')
        self.assertTrue(timeout['tests_passed']);self.assertTrue(timeout['solved_by_tests'])
        self.assertFalse(timeout['primary_solved']);self.assertFalse(timeout['strict_solved'])
        for s in levels:self.assertGreater(s['tests_passing_at_cutoff'],s['solved'])
        # Live/probe behavior remains the historical hidden-test metric.
        live,_=summarize(paths,allow_pending=True)
        self.assertGreater(next(s for s in live if s['level']=='c16')['solved'],3)
        with tempfile.TemporaryDirectory() as tmp:
            write_matched(Path(tmp),levels,rows)
            self.assertTrue((Path(tmp)/'matched_summary.csv').exists())

    def test_wilson_and_probability_ordered_two_sided_fisher(self):
        self.assertAlmostEqual(wilson(0,3)[1],.5614970317550454)
        self.assertEqual(wilson(0,3)[0],0)
        self.assertAlmostEqual(fisher_exact(1,9,11,3),.0027594561852200836)
        self.assertEqual(fisher_exact(7,22,7,22),1)
        self.assertEqual(fisher_exact(3,26,7,22),fisher_exact(7,22,3,26))
        with self.assertRaises(ValueError):wilson(0,0)

    @unittest.skipIf(not (ROOT / 'results/atlas/scored/anecdotal/c1/runs.json').is_file(), 'requires archived anecdotal run records, not distributed')
    def test_anecdotal_c1_is_three_historical_attempts_not_a_completed_queue(self):
        levels,_=summarize([ROOT/'results/atlas/scored/anecdotal/c1/runs.json'],[ROOT/'results/raw/c1/samples.jsonl'],strict=True)
        value=levels[0]
        self.assertEqual((value['runs'],value['solved'],value['tests_passing_at_cutoff']),(3,0,1))
        self.assertTrue(value['anecdotal']);self.assertTrue(value['planned_level_dropped'])
        self.assertIsNone(value['engine_ttft_p50_s'])

    def test_incomplete_usage_is_partial_never_a_zero_or_full_total(self):
        events=[dict(event='request',request_id='a'),dict(event='response',request_id='a',token_source='proxy',tokens_in=100,tokens_out=8,tokens_cached=60),
                dict(event='request',request_id='b')]
        result=usage(events)
        self.assertFalse(result['complete']);self.assertEqual(result['missing_request_ids'],['b'])
        self.assertEqual(result['known'],dict(tokens_in=100,tokens_out=8,tokens_cached=60,tokens_uncached_in=40))
        self.assertFalse(usage([])['complete'])

    def test_exact_gpu_window_keeps_microseconds_and_gaps(self):
        rows=[dict(study_session=7,started_at='2026-10-18T00:00:00.001Z',ended_at='2026-10-18T00:00:01.002Z'),
              dict(study_session=7,started_at='2026-10-18T00:00:02.003Z',ended_at='2026-10-18T00:00:03.004Z')]
        result=exact_window(rows)
        self.assertEqual(result['microseconds'],3003000)
        self.assertEqual(result['gpu_hours_fraction'],dict(numerator=3003000,denominator=3600000000))

    @unittest.skipIf(not (ROOT / 'results/atlas/scored/live/c16/runs.json').is_file(), 'requires archived live run records and native grading audits, not distributed')
    def test_all_synced_c26_reviews_are_bound_to_pinned_calls_and_audits(self):
        inventory=audit_inventory(ROOT)
        self.assertEqual({r['level'] for r in inventory},{'c16','c8','c4'})
        self.assertTrue(all(r['accepted'] and r['claim']=='none' for r in inventory))

    @unittest.skipIf(not (ROOT / 'results/atlas/scored/live/c16/runs.json').is_file(), 'requires archived live run records and native grading audits, not distributed')
    def test_finalization_refuses_missing_review_before_writing(self):
        report=json.loads((ROOT/'results/atlas/scored/live/c8/runs.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'input.json';path.write_text(json.dumps(report))
            with self.assertRaises(FileNotFoundError):finalize([path],root)
            self.assertFalse((root/'results/atlas/scored/final').exists())


if __name__=='__main__':unittest.main()
