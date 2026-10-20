import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from post_final_006 import category,counter_delta,panel,sha

class PostFinalTests(unittest.TestCase):
    def test_caps_and_original_tamper_survive_passing_sensitivity_tests(self):
        for reason in ('timeout','turn_cap','token_cap'):
            self.assertEqual(category(dict(end_reason=reason,tamper=False),True),reason)
        self.assertEqual(category(dict(end_reason='completed',tamper=True),True),'tamper')
        self.assertEqual(category(dict(end_reason='completed',tamper=False),True),'solved')

    def test_cumulative_level_delta_subtracts_prior_level_and_rejects_resets(self):
        records=[dict(ts=0,boundary='before',prefix_queries=100,prefix_hits=80),dict(ts=2,prefix_queries=150,prefix_hits=110),dict(ts=4,boundary='after',prefix_queries=150,prefix_hits=110)]
        result=counter_delta(records,1,3)
        self.assertEqual((result['prompt_tokens'],result['cached_input_tokens'],result['uncached_input_tokens']),(50,30,20))
        records[1]['prefix_queries']=90
        with self.assertRaisesRegex(ValueError,'reset'):counter_delta(records,1,3)

    def test_unlabelled_c16_tail_needs_post_end_sample_and_cross_end_plateau(self):
        records=[dict(ts=0,boundary='before',prefix_queries=0,prefix_hits=0),dict(ts=2,prefix_queries=100,prefix_hits=70),dict(ts=4,prefix_queries=100,prefix_hits=70)]
        self.assertTrue(counter_delta(records,1,3)['complete'])
        with self.assertRaisesRegex(ValueError,'cover level end'):counter_delta(records,1,5)
        records[-1]['prefix_queries']=110
        with self.assertRaisesRegex(ValueError,'stable endpoint'):counter_delta(records,1,3)

    def test_all_13_real_native_regrades_and_replacement_panel(self):
        value=json.loads((ROOT/'results/analysis/symlink_sensitivity.json').read_text())
        self.assertEqual(len(value['attempts']),13)
        self.assertEqual(sum(r['tests_passed'] for r in value['attempts']),4)
        self.assertTrue(all(not r['strict_solved'] for r in value['attempts']))
        for row in value['levels']:
            self.assertEqual(row['official_export_sha256'],sha(ROOT/f'results/atlas/scored/final/{row["level"]}/runs.json'))
            self.assertEqual(row['sensitivity']['graded_tasks'],30)
            self.assertEqual(row['sensitivity']['solved'],row['official']['solved'])

    def test_engine_totals_and_proxy_gaps_are_measured_separately(self):
        value=json.loads((ROOT/'results/analysis/engine_input_totals.json').read_text())
        expected={'c16':(24010346,22397440,1612906),'c8':(36358417,34394880,1963537),'c4':(52060003,49364224,2695779)}
        for row in value['levels']:
            self.assertEqual(tuple(row[k] for k in ('prompt_tokens','cached_input_tokens','uncached_input_tokens')),expected[row['level']])
            self.assertEqual(row['prompt_gap'],row['cached_gap']+row['uncached_gap'])
            self.assertTrue(row['complete']);self.assertFalse(row['output_complete'])
        self.assertFalse(value['c1']['complete'])

if __name__=='__main__':unittest.main()
