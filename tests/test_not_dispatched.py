import copy
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.llm import LLMNotDispatched
from vision_rsi.training_cli import summary


class NotDispatchedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Sessions(self.root/'sessions')
        self.session=self.store.create('fixture','Keep the actual requirements')['session_id']
        self.valid=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
        self.config={'model':'fixture','base_url':'https://example.invalid','api_key_env':'TEST_LLM_KEY',
                     'usage_ledger':str(self.root/'usage.sqlite3')}

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_zero_cap_preserves_user_turns_and_requirements_without_claiming_unknown_api(self,network):
        original=self.store.define(self.session,self.valid)
        config=dict(self.config,usage_call_limit=0)
        for message in ('New requirement must be interpreted before running',None):
            with self.assertRaises(LLMNotDispatched):self.store.clarify(self.session,config,message)
        result=self.store.show(self.session)
        self.assertEqual(result['versions'],original['versions'])
        self.assertEqual(sum(t.get('content')=='New requirement must be interpreted before running' for t in result['turns']),1)
        self.assertTrue(result['pending_request']);self.assertTrue(result['clarification_not_dispatched'])
        self.assertFalse(result['api_outcome_uncertain']);self.assertEqual(result['unsettled_api_request_ids'],[])
        self.assertNotIn('abandon-request',summary(result));network.assert_not_called()
        with self.store.db() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT state FROM clarification_requests')],['not_dispatched']*2)
        from vision_rsi.harness import build
        from vision_rsi.training_plan import prepare
        from vision_rsi.campaign import advance
        with self.assertRaisesRegex(ValueError,'unprocessed'):build(result,self.root/'harness')
        with self.assertRaisesRegex(ValueError,'unprocessed'):advance(result,{},self.root/'campaigns')
        plan=prepare(result,{},self.root/'plans')
        self.assertTrue(any('需求请求尚未处理' in reason for reason in plan['blockers']))

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_explicit_retry_after_local_ledger_failure_requires_no_abandon_or_budget_reset(self,network):
        path=Path(self.config['usage_ledger']);path.mkdir()
        with self.assertRaises(LLMNotDispatched):self.store.clarify(self.session,self.config,'Keep this user text')
        path.rmdir()
        response={'model':'fixture','content':json.dumps(self.valid),'usage':{}}
        network.return_value=io.BytesIO(json.dumps({'model':'fixture','choices':[{'message':{'content':response['content']}}],'usage':{}}).encode())
        result=self.store.clarify(self.session,self.config)
        self.assertFalse(result['pending_request']);self.assertFalse(result['api_outcome_uncertain'])
        self.assertEqual(result['versions'][-1]['contract'],self.valid)
        self.assertEqual(sum(t.get('content')=='Keep this user text' for t in result['turns']),1)
        network.assert_called_once()

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_unsent_format_correction_applies_only_received_draft_without_unknown_response(self,network):
        broken=copy.deepcopy(self.valid);broken['assumptions']={'invalid':'format'}
        network.return_value=io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(broken)}}],'usage':{}}).encode())
        result=self.store.clarify(self.session,dict(self.config,usage_call_limit=1))
        self.assertFalse(result['pending_request'])
        latest=result['versions'][-1]
        self.assertEqual(latest['contract'],broken)
        self.assertEqual(len(latest['response_ids']),1)
        self.assertIn('format_correction_not_dispatched',latest)
        self.assertTrue(any('格式修正请求未发送' in issue for issue in latest['issues']))
        self.assertFalse(latest['format_correction_attempted'])
        network.assert_called_once()

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen',side_effect=TimeoutError)
    def test_real_dispatch_uncertainty_still_blocks_retry(self,network):
        with self.assertRaises(RuntimeError):self.store.clarify(self.session,self.config)
        result=self.store.show(self.session)
        self.assertTrue(result['api_outcome_uncertain']);self.assertFalse(result['clarification_not_dispatched'])
        with self.assertRaisesRegex(RuntimeError,'uncertain'):self.store.clarify(self.session,self.config)
        network.assert_called_once()

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_explicit_user_definition_can_supersede_unsent_requirements_without_api_or_budget_reset(self,network):
        config=dict(self.config,usage_call_limit=0)
        with self.assertRaises(LLMNotDispatched):self.store.clarify(self.session,config)
        with self.assertRaises(ValueError):self.store.define(self.session,self.valid,origin='agent_defaults')
        result=self.store.define(self.session,self.valid)
        self.assertFalse(result['pending_request'])
        self.assertTrue(result['versions'][-1]['supersedes_not_dispatched_requirements'])
        from vision_rsi.llm_usage import snapshot
        report=snapshot(self.config['usage_ledger'])
        self.assertEqual(report['project_call_limit'],0);self.assertEqual(report['calls'],0)
        network.assert_not_called()

    @patch.dict('os.environ',{'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_local_settlement_failure_after_dispatch_is_not_misclassified_as_unsent(self,network):
        network.return_value=io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(self.valid)}}],'usage':{}}).encode())
        with patch('vision_rsi.llm_usage.UsageLedger.finish',side_effect=sqlite3.OperationalError('fixture settlement failed')):
            with self.assertRaises(sqlite3.Error):self.store.clarify(self.session,self.config)
        result=self.store.show(self.session)
        self.assertTrue(result['api_outcome_uncertain']);self.assertFalse(result['clarification_not_dispatched'])
        with self.assertRaisesRegex(RuntimeError,'uncertain'):self.store.clarify(self.session,self.config)
        network.assert_called_once()
