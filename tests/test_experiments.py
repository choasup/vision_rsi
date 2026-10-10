import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from test_acceptance import evidence,wrap
from test_coco_train import fixture_recipe
from vision_rsi.experiments import compile_plan,propose_next
from vision_rsi.runner import digest


def proposal():
    return {'hypothesis':'Lower learning rate reduces instability','reasoning':'Measured score is below the original target; instability is only a hypothesis',
            'recipe_changes':{'learning_rate':.0005},'expected_result':'Measure AP again without assuming improvement','failure_criteria':'No repeatable improvement within the same budget'}


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        parent,receipt=evidence(score=42)
        parent.update(task_id='task',session_id='session',status='ready_to_submit',blockers=[],
                      scheduler={'gpu_devices':[0],'timeout_seconds':40,'gpu_hours_budget':1})
        parent['contract']['budget']={'gpu_hours':1}
        parent['recipe']=dict(fixture_recipe('.'),coco_root='/remote/coco',weights='/remote/weights.pth',fixture=False,
                              acceptance_threshold=60,val_annotations_sha256='a'*64)
        result=json.loads(base64.b64decode(receipt['reports']['result.json']['base64']))
        result['identity']['recipe']=parent['recipe'];result['identity_hash']=digest(result['identity'])
        receipt['reports']['result.json']=wrap(result);receipt['run_id']='train-'+'a'*32
        self.parent=parent
        path=self.root/'parent.json';path.write_text(json.dumps(parent));rp=self.root/'receipt.json';rp.write_text(json.dumps(receipt))
        self.record={'run_id':receipt['run_id'],'status':'completed','actual_gpu_hours':.01,'plan_id':digest(parent),
                     'details':{'plan_path':str(path),'receipt_path':str(rp),'deployment':{'directory':'/workspace/releases/frozen'}}}
        self.runs=MagicMock();self.runs.remaining.return_value=.5
        self.llm={'model':'fixture','base_url':'https://fixture.invalid'}

    def test_method_change_keeps_data_model_threshold_sources_and_budget_frozen(self):
        original=copy.deepcopy(self.parent)
        plan=compile_plan(self.parent,self.record,proposal(),.003,self.root/'plans')
        self.assertEqual(self.parent,original)
        self.assertEqual(plan['recipe']['learning_rate'],.0005)
        for field in ('detector','weights','weights_sha256','coco_root','val_annotations_sha256','seed','world_size','fixture','acceptance_threshold'):
            self.assertEqual(plan['recipe'][field],original['recipe'][field])
        self.assertEqual(plan['contract'],original['contract']);self.assertEqual(plan['source_hashes'],original['source_hashes'])
        self.assertLessEqual((plan['scheduler']['timeout_seconds']+5)/3600,.003)
        self.assertEqual(digest(json.loads(Path(plan['plan_path']).read_text())),plan['plan_id'])

    def test_forbidden_changes_and_insufficient_budget_rejected(self):
        for field,value in [('acceptance_threshold',1),('fixture',True),('weights','/different'),('coco_root','/other'),('world_size',8),('seed',9)]:
            changed=proposal();changed['recipe_changes'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):compile_plan(self.parent,self.record,changed,.5,self.root/'plans')
        with self.assertRaises(ValueError):compile_plan(self.parent,self.record,proposal(),.001,self.root/'plans')

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_proposal_response_reused_and_original_receipt_rechecked(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal()),'model':'fixture'}
        first=propose_next(self.record,self.runs,self.llm,self.root/'research','request-one')
        self.assertEqual(first['status'],'ready_to_submit')
        self.assertEqual(first,propose_next(self.record,self.runs,self.llm,self.root/'research','request-one'))
        client.return_value.complete.assert_called_once()
        Path(self.record['details']['plan_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'parent Training plan changed'):
            propose_next(self.record,self.runs,self.llm,self.root/'research','request-one')

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_uncertain_api_not_retried_and_exhausted_budget_never_calls(self,client):
        client.return_value.complete.side_effect=TimeoutError('response uncertain')
        with self.assertRaises(TimeoutError):propose_next(self.record,self.runs,self.llm,self.root/'research','request-two')
        with self.assertRaisesRegex(RuntimeError,'Uncertain experiment API'):
            propose_next(self.record,self.runs,self.llm,self.root/'research','request-two')
        client.return_value.complete.assert_called_once()
        self.runs.remaining.return_value=0
        result=propose_next(self.record,self.runs,self.llm,self.root/'research','request-three')
        self.assertEqual(result['status'],'budget_exhausted');client.return_value.complete.assert_called_once()

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_unsafe_model_proposal_recorded_but_never_ready(self,client):
        changed=proposal();changed['recipe_changes']['acceptance_threshold']=1
        client.return_value.complete.return_value={'content':json.dumps(changed)}
        result=propose_next(self.record,self.runs,self.llm,self.root/'research','request-four')
        self.assertEqual(result['status'],'proposal_rejected')
        self.assertFalse(result['training_performed'])
