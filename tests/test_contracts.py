import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from vision_rsi.contracts import Sessions,issues,validate_sample,validate_schema

class ContractTests(unittest.TestCase):
    def setUp(self): self.contract=json.loads(Path('examples/interface-contract.json').read_text())
    def test_joint_video_and_output_contract(self):
        self.assertEqual(issues(self.contract),[])
        self.assertTrue(validate_sample(self.contract,self.contract['example_input'])['valid'])
        self.contract['example_input']['inputs']['views']['items'].pop()
        self.assertTrue(issues(self.contract))
        with self.assertRaises(ValueError):validate_schema(self.contract['output_schema'],{'defects':[{'label':'scratch','start_seconds':-1}]})
    def test_persistent_versions_and_missing_policy(self):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root);session=store.create('inspection','goal')['session_id']
            self.assertEqual(store.define(session,self.contract)['status'],'ready_for_harness')
            self.contract['inputs']['clip']['processing'].pop('temporal')
            updated=Sessions(root).define(session,self.contract)
            self.assertEqual(updated['status'],'clarifying')
            self.assertEqual(len(updated['versions']),2)
            self.assertEqual(updated['turns'][0]['content'],'goal')
    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_clarification_and_uncertain_call(self,client):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root);session=store.create('inspection','goal')['session_id']
            client.return_value.complete.return_value={'content':json.dumps(self.contract),'usage':{'total_tokens':10}}
            result=store.clarify(session,{'model':'fixture'},'Use joint images')
            self.assertEqual(result['status'],'ready_for_harness')
            self.assertEqual(result['turns'][1]['content'],'Use joint images')
            client.return_value.complete.side_effect=RuntimeError('timeout')
            with self.assertRaises(RuntimeError):store.clarify(session,{'model':'fixture'},'change')
            before=client.return_value.complete.call_count
            with self.assertRaises(RuntimeError):store.clarify(session,{'model':'fixture'})
            self.assertEqual(client.return_value.complete.call_count,before)
