import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions


class ClarificationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Sessions(self.temp.name);self.session=self.store.create('inspection','Original task')['session_id']
        self.contract=json.loads(Path('examples/interface-contract.json').read_text())

    def test_actual_process_exit_after_receipt_recovers_without_network(self):
        script="""
import json,os,sys
from unittest.mock import patch
from vision_rsi.contracts import Sessions
store=Sessions(sys.argv[1])
response={'content':json.dumps(json.load(open('examples/interface-contract.json'))),'usage':{'total_tokens':30}}
with patch('vision_rsi.contracts.OpenAICompatibleClient') as client:
 client.return_value.complete.return_value=response
 store._finish_response=lambda *args,**kwargs:os._exit(73)
 store.clarify(sys.argv[2],{'model':'fixture'},'Use the specified interface')
"""
        child=subprocess.run([sys.executable,'-c',script,self.temp.name,self.session],capture_output=True,timeout=20)
        self.assertEqual(child.returncode,73,child.stderr.decode(errors='replace'))
        pending=self.store.show(self.session);identity=pending['pending_request_id']
        self.assertTrue(pending['pending_request']);self.assertEqual(pending['pending_response_count'],1)
        cli=subprocess.run([sys.executable,'-m','vision_rsi','training','recover','--session-id',self.session,
                            '--request-id',identity,'--sessions',self.temp.name,'--config','nonexistent-config.json','--json'],
                           capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(cli.returncode,0,cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['versions'][-1]['contract'],self.contract)
        with patch('vision_rsi.contracts.OpenAICompatibleClient') as client:
            result=Sessions(self.temp.name).resolve_request(self.session,identity)
            repeated=self.store.resolve_request(self.session,identity)
            client.assert_not_called()
        self.assertEqual(result['versions'][-1]['contract'],self.contract)
        self.assertFalse(result['pending_request']);self.assertEqual(len(repeated['versions']),1)
        self.assertIn(identity,result['unsettled_api_request_ids'])
        self.assertEqual(result['turns'][1]['content'],'Use the specified interface')

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_unknown_outcome_requires_explicit_abandon_and_retains_turns(self,client):
        client.return_value.complete.side_effect=RuntimeError('timeout')
        with self.assertRaises(RuntimeError):self.store.clarify(self.session,{'model':'fixture'},'Additional constraints')
        pending=self.store.show(self.session);identity=pending['pending_request_id']
        with self.assertRaisesRegex(ValueError,'No recorded response'):self.store.resolve_request(self.session,identity)
        with self.assertRaises(ValueError):self.store.resolve_request(self.session,'0'*32,abandon=True)
        result=self.store.resolve_request(self.session,identity,abandon=True)
        self.assertFalse(result['pending_request']);self.assertIn(identity,result['unsettled_api_request_ids'])
        self.assertEqual(result['turns'][-1]['content'],'Additional constraints')
        self.assertEqual(result,self.store.resolve_request(self.session,identity,abandon=True))
        client.return_value.complete.assert_called_once()

    def test_active_lock_blocks_recovery_and_abandonment(self):
        with self.store.request_lock(self.session):
            for abandon in (False,True):
                with self.assertRaises(RuntimeError):
                    Sessions(self.temp.name).resolve_request(self.session,'0'*32,abandon=abandon)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_recovered_draft_still_requires_requirement_change_review(self,client):
        self.store.define(self.session,self.contract)
        changed=json.loads(json.dumps(self.contract));changed['acceptance']['threshold']+=1
        client.return_value.complete.return_value={'content':json.dumps(changed)}
        with patch.object(self.store,'_finish_response',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):self.store.clarify(self.session,{'model':'fixture'})
        identity=self.store.show(self.session)['pending_request_id']
        result=self.store.resolve_request(self.session,identity)
        self.assertEqual(result['status'],'requirements_review')
        self.assertEqual(result['versions'][-1]['contract'],self.contract)
        self.assertEqual(result['versions'][-1]['proposed_contract'],changed)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_changed_context_is_not_overwritten(self,client):
        client.return_value.complete.return_value={'content':json.dumps(self.contract)}
        with patch.object(self.store,'_finish_response',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):self.store.clarify(self.session,{'model':'fixture'})
        identity=self.store.show(self.session)['pending_request_id']
        with self.store.db() as db:db.execute('UPDATE sessions SET turns=? WHERE id=?',('[]',self.session))
        with self.assertRaisesRegex(ValueError,'context changed'):self.store.resolve_request(self.session,identity)
        self.assertTrue(self.store.show(self.session)['pending_request'])
