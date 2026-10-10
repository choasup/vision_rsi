import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions,validate_schema,validate_schema_definition


class ContractFormatRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Sessions(self.temp.name)
        self.session=self.store.create('inspection','Joint images and video')['session_id']
        self.valid=json.loads(Path('examples/interface-contract.json').read_text())
        self.broken=copy.deepcopy(self.valid);self.broken['assumptions']={'choice':'use defaults'}

    def test_fixed_length_boxes_are_validated(self):
        schema={'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}
        validate_schema(schema,[0,0,1,1])
        for values in ([0,0,1],[0,0,1,1,1]):
            with self.assertRaises(ValueError):validate_schema(schema,values)
        for invalid in ({**schema,'minItems':True},{**schema,'maxItems':-1},{**schema,'minItems':5},{'type':'string','minItems':1}):
            with self.assertRaises(ValueError):validate_schema_definition(invalid)

    def test_coco_adapter_checks_sparse_category_ids_and_empty_predictions(self):
        from vision_rsi.training_plan import prepare
        contract=json.loads(Path('examples/coco-task.json').read_text())
        contract['output_schema']={'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{'category_id':{'type':'integer','maximum':80},'bbox':{'type':'array','items':{'type':'number'}},'score':{'type':'number'}}}}}}
        session={'session_id':'test','task_id':'test','versions':[{'version':1,'contract':contract}]}
        result=prepare(session,{'remote':{}},Path(self.temp.name)/'plans')
        self.assertTrue(any('不兼容' in item for item in result['blockers']))

    @staticmethod
    def response(contract):return {'content':json.dumps(contract),'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_known_schema_error_is_repaired_once_and_each_response_is_durable(self,client):
        client.return_value.complete.side_effect=[self.response(self.broken),self.response(self.valid)]
        result=self.store.clarify(self.session,{'model':'fixture'})
        latest=result['versions'][-1]
        self.assertEqual(result['status'],'ready_for_harness');self.assertTrue(latest['format_correction_attempted'])
        self.assertEqual(len(latest['response_usage']),2);self.assertEqual(client.return_value.complete.call_count,2)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM clarification_responses').fetchone()[0],2)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_correction_cannot_change_acceptance_or_joint_semantics(self,client):
        for field in ('threshold','semantics'):
            with self.subTest(field=field):
                session=self.store.create('test','Requirements must survive repair')['session_id']
                changed=copy.deepcopy(self.valid)
                if field=='threshold':changed['acceptance']['threshold']=0
                else:changed['inputs']['views']['min_items']=1
                client.return_value.complete.side_effect=[self.response(self.broken),self.response(changed)]
                result=self.store.clarify(session,{'model':'fixture'})
                self.assertEqual(result['versions'][-1]['contract'],self.broken)
                self.assertTrue(any('解析失败' in item for item in result['versions'][-1]['issues']))

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_missing_budget_is_not_repaired_or_invented(self,client):
        contract=copy.deepcopy(self.valid);contract['budget']=None
        client.return_value.complete.return_value=self.response(contract)
        result=self.store.clarify(self.session,{'model':'fixture'})
        self.assertEqual(result['status'],'task_defined');self.assertIsNone(result['versions'][-1]['contract']['budget'])
        client.return_value.complete.assert_called_once()

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_uncertain_repair_preserves_received_response_and_does_not_retry(self,client):
        client.return_value.complete.side_effect=[self.response(self.broken),RuntimeError('timeout')]
        with self.assertRaises(RuntimeError):self.store.clarify(self.session,{'model':'fixture'})
        self.assertTrue(self.store.show(self.session)['pending_request'])
        with self.store.db() as db:
            raw=db.execute('SELECT response FROM clarification_responses').fetchone()[0]
        self.assertEqual(json.loads(raw)['content'],json.dumps(self.broken))
        with self.assertRaises(RuntimeError):self.store.clarify(self.session,{'model':'fixture'})
        self.assertEqual(client.return_value.complete.call_count,2)
