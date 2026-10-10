from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.llm import OpenAICompatibleClient
from vision_rsi.llm_usage import UsageLedger,snapshot


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'usage.sqlite3'
        self.config={'base_url':'https://example.invalid','model':'fixture','api_key_env':'TEST_LLM_KEY',
                     'usage_ledger':str(self.path)}

    def test_pending_and_bad_usage_never_become_zero_tokens(self):
        ledger=UsageLedger(str(self.path))
        ledger.reserve(b'first','fixture')
        for usage in ({},{'prompt_tokens':True,'completion_tokens':2,'total_tokens':3},
                      {'prompt_tokens':1,'completion_tokens':2,'total_tokens':4}):
            ledger.finish(ledger.reserve(b'next','fixture'),usage)
        report=snapshot(str(self.path))
        self.assertEqual(report['calls'],4);self.assertEqual(report['unknown_token_calls'],4)
        self.assertTrue(all(r['reported_total_tokens'] is None for r in report['groups']))
        self.assertFalse(report['budget_enforced']);self.assertFalse(report['historical_backfill_complete'])

    def test_concurrent_clients_share_append_only_records_and_exact_usage(self):
        ledger=UsageLedger(str(self.path))
        def call(i):
            identity=ledger.reserve(str(i).encode(),'fixture')
            ledger.finish(identity,{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5})
            return identity
        with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(call,range(20)))
        self.assertEqual(len(set(ids)),20)
        report=snapshot(str(self.path));self.assertEqual(report['calls'],20)
        self.assertEqual(report['groups'][0]['reported_total_tokens'],100)
        with self.assertRaises(ValueError):ledger.finish(ids[0],{})
        self.assertEqual(snapshot(str(self.path)),report)

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_client_records_before_network_and_links_response_without_secrets(self,opened):
        def network(*args,**kwargs):
            self.assertEqual(snapshot(str(self.path))['unknown_token_calls'],1)
            return io.BytesIO(json.dumps({'model':'fixture','choices':[{'message':{'content':'private response'}}],
                                          'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}}).encode())
        opened.side_effect=network
        result=OpenAICompatibleClient(self.config).complete([{'role':'user','content':'private prompt'}])
        self.assertEqual(len(result['usage_record_id']),32)
        report=snapshot(str(self.path));self.assertEqual(report['unknown_token_calls'],0)
        self.assertEqual(report['groups'][0]['reported_total_tokens'],5)
        raw=self.path.read_bytes()
        for value in (b'fixture-secret',b'private response',b'private prompt'):self.assertNotIn(value,raw)

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen',side_effect=TimeoutError)
    def test_unknown_network_outcome_retained_without_retry(self,opened):
        with self.assertRaises(RuntimeError):OpenAICompatibleClient(self.config).complete([])
        opened.assert_called_once()
        report=snapshot(str(self.path));self.assertEqual(report['unknown_token_calls'],1)
        self.assertEqual(report['groups'][0]['status'],'uncertain')

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_unwritable_ledger_or_invalid_path_prevents_network(self,opened):
        self.path.mkdir()
        with self.assertRaises(sqlite3.Error):OpenAICompatibleClient(self.config).complete([])
        for path in ('relative.sqlite3',''):
            with self.assertRaises(ValueError):OpenAICompatibleClient(dict(self.config,usage_ledger=path)).complete([])
        opened.assert_not_called()

    def test_readonly_audit_does_not_create_missing_ledger(self):
        with self.assertRaises(sqlite3.Error):snapshot(str(self.path))
        self.assertFalse(self.path.exists())
