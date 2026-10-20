"""Served-setting proof against the captured session-3 production vLLM record."""
import ast
import json
import io
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch, Mock
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import fake_engine_006 as fake
from session4_flow_006 import FROZEN_SERVER, frozen_server_settings, validate_server

REAL = ROOT/'results/droplet_logs/current_server.json'
WEIGHTS = ROOT/'results/droplet_logs/weights_provenance.json'
FAILED_FAKE = ROOT/'results/rehearsal/logs/current_server.json'


class ServedSettingsTests(unittest.TestCase):
    def real(self):
        # Read original captured results directly, not a hand-constructed nominal dict.
        return json.loads(REAL.read_text())

    def test_actual_session3_vllm_metadata_and_provenance_pass(self):
        record = self.real()
        provenance = json.loads(WEIGHTS.read_text())
        self.assertEqual(record['hf_repo'],provenance['model'])
        self.assertEqual(record['model_revision'],provenance['revision'])
        self.assertEqual(record['weights_sha256'],provenance['weights_sha256'])
        self.assertEqual(validate_server(record),FROZEN_SERVER)
        # Cross-check the wrapper/provenance capture against vLLM's own API log.
        native_log=ROOT/'results/droplet_logs'/Path(record['server_log']).name
        line=next(s for s in native_log.read_text().splitlines() if 'non-default args: ' in s)
        native=ast.literal_eval(line.split('non-default args: ',1)[1])
        self.assertEqual(native['model'],record['hf_repo'])
        self.assertEqual(native['dtype'],'bfloat16')
        self.assertEqual(native['max_model_len'],record['max_model_len'])
        for field in ('tool_call_parser','reasoning_parser','enable_auto_tool_choice','enable_prompt_tokens_details'):
            self.assertEqual(native[field],FROZEN_SERVER['server_args.'+field])

    def test_failure_is_fake_precision_metadata_not_old_comparison_logic(self):
        failed = json.loads(FAILED_FAKE.read_text());real = self.real()
        old = ('engine','hf_repo','max_model_len','weights_precision')
        self.assertEqual([k for k in old if real[k]!=failed[k]],['weights_precision'])
        self.assertIsNone(failed['weights_precision'])
        self.assertEqual(real['weights_precision'],'bf16')
        with self.assertRaises(ValueError) as error:validate_server(failed)
        text=str(error.exception)
        self.assertIn('weights_precision: expected="bf16", actual=null [MISMATCH]',text)
        self.assertIn('engine: expected="vllm", actual="vllm" [OK]',text)
        self.assertEqual(len(text.splitlines()),len(FROZEN_SERVER)+1)
        for field in FROZEN_SERVER:
            self.assertIn('  '+field+': expected=',text)
            self.assertIn('actual=',next(line for line in text.splitlines() if line.startswith('  '+field+':')))

    def test_genuine_frozen_mismatches_fail_individually(self):
        cases = [('engine','sglang'),('hf_repo','wrong/model'),('model_revision','wrong-revision'),
                 ('max_model_len',32768),('weights_precision','fp16')]
        for field,value in cases:
            with self.subTest(field=field):
                record=self.real();record[field]=value
                with self.assertRaises(ValueError) as error:validate_server(record)
                self.assertIn(field+': expected=',str(error.exception))
                line=next(s for s in str(error.exception).splitlines() if s.startswith('  '+field+':'))
                self.assertIn('[MISMATCH]',line)

    def test_launch_precision_context_parsers_and_reporting_cannot_drift(self):
        mutations = [('--dtype bfloat16','--dtype float16','server_args.dtype'),
            ('--max-model-len 131072','--max-model-len 4096','server_args.max_model_len'),
            ('--tool-call-parser qwen3_coder','--tool-call-parser other','server_args.tool_call_parser'),
            ('--reasoning-parser qwen3','--reasoning-parser other','server_args.reasoning_parser'),
            ('--enable-auto-tool-choice','','server_args.enable_auto_tool_choice'),
            ('--enable-prompt-tokens-details','','server_args.enable_prompt_tokens_details'),
            ('--enable-prompt-tokens-details','--no-enable-prompt-tokens-details','server_args.enable_prompt_tokens_details'),
            ('--enable-prompt-tokens-details','--enable-prompt-tokens-details=false','server_args.enable_prompt_tokens_details')]
        for before,after,field in mutations:
            with self.subTest(field=field,after=after):
                record=self.real();record['server_args']=record['server_args'].replace(before,after)
                with self.assertRaises(ValueError) as error:validate_server(record)
                self.assertIn(field+': expected=',str(error.exception))
                line=next(s for s in str(error.exception).splitlines() if s.startswith('  '+field+':'))
                self.assertIn('[MISMATCH]',line)

    def test_only_frozen_fields_are_compared(self):
        record=self.real()
        record.update(container_id='different-container',image_id='different-container-image-id',
            pid=9999,started_at='2030-01-01T00:00:00Z',droplet_ip='192.0.2.5',token='new-token',
            server_log='different/log',engine_version='session-dependent-provenance',rehearsal=True,
            weights_sha256={'not-a-comparison-field':'native hashes are separate provenance'})
        record['server_args']=record['server_args'].replace('--host 0.0.0.0 --port 8000','--host localhost --port 9999')
        self.assertEqual(validate_server(record),FROZEN_SERVER)
        # Equivalent parser argument spelling/precision aliases are still the same settings.
        record['server_args']=record['server_args'].replace('--tool-call-parser qwen3_coder','--tool-call-parser=qwen3_coder').replace('--dtype bfloat16','--dtype=bf16')
        self.assertEqual(validate_server(record),FROZEN_SERVER)

    def test_missing_or_malformed_metadata_has_complete_diagnostics(self):
        for args in (None,'"unterminated',True,[]):
            with self.subTest(args=args):
                record=self.real();record['server_args']=args
                with self.assertRaises(ValueError) as error:validate_server(record)
                self.assertEqual(len(str(error.exception).splitlines()),len(FROZEN_SERVER)+1)
        record=self.real();record.pop('model_revision')
        with self.assertRaisesRegex(ValueError,'model_revision.*actual=null.*MISMATCH'):validate_server(record)

    def test_start_writes_the_same_metadata_builder_used_by_local_check(self):
        token='owned-start-token'
        response=json.dumps({'data':[{'rehearsal_token':token}]}).encode()
        process=Mock(pid=4321);process.poll.return_value=None
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,REHEARSAL='1'), \
                patch.object(sys,'argv',['fake_engine_006.py','start','--root',tmp,'--engine','vllm']), \
                patch.object(fake,'stop'),patch.object(fake.subprocess,'Popen',return_value=process), \
                patch.object(fake.uuid,'uuid4',return_value=SimpleNamespace(hex=token)), \
                patch.object(fake.urllib.request,'urlopen',return_value=io.BytesIO(response)):
            fake.main()
            record=json.loads((Path(tmp)/'results/rehearsal/logs/current_server.json').read_text())
            self.assertEqual(record,fake.server_metadata('vllm',token=token))
            self.assertEqual(validate_server(record),FROZEN_SERVER)

    def test_fake_vllm_reports_the_recorded_real_frozen_shape(self):
        real=self.real();record=fake.server_metadata('vllm',token='owned-rehearsal-token')
        self.assertEqual(validate_server(record),frozen_server_settings(real))
        for key in ('engine','cfg','hf_repo','model_revision','weights_precision','max_model_len',
                    'server_args','kv_cache_dtype','serve_env','gpu_memory_utilization','knob_set'):
            self.assertEqual(record[key],real[key],key)
        self.assertTrue(record['rehearsal']);self.assertTrue(record['fixture'])
        self.assertEqual(record['engine_version'],'cpu-rehearsal-1')
        self.assertNotIn('image_id',record);self.assertNotIn('weights_sha256',record)
        self.assertEqual(record['token'],'owned-rehearsal-token')
        # Return a fresh record per server; callers cannot mutate future launches.
        record['weights_precision']=None
        self.assertEqual(validate_server(fake.server_metadata('vllm')),FROZEN_SERVER)


if __name__=='__main__':unittest.main()
