import copy
import tempfile
import unittest

from vision_rsi.task_harness import plan, configured_resources
from vision_rsi.classification_eval import evaluate


class TaskHarnessTests(unittest.TestCase):
    def test_classification_plan_preserves_contract_without_coco_substitution(self):
        contract={'goal':'猫狗分类','inputs':{'image':{'type':'image','required':True}},
                  'output_schema':{'type':'object','properties':{'label':{'type':'string'},'confidence':{'type':'number'}}},
                  'acceptance':{'metric':'accuracy','threshold':80,'direction':'maximize','evaluation_protocol':'heldout classification percent'}}
        session={'task_id':'test','session_id':'a'*32,'versions':[{'version':1,'contract':contract}]}
        original=copy.deepcopy(session)
        with tempfile.TemporaryDirectory() as root:
            first=plan(session,root)
            self.assertEqual(first,plan(session,root))
            self.assertEqual(first['task_family'],'image_classification')
            self.assertTrue(first['missing_backend'])
            self.assertEqual(first['contract'],contract)
            self.assertFalse(first['training_performed'])
            self.assertFalse(first['resource_requirements']['dataset_bound'])
            self.assertEqual(first['resource_requirements']['class_labels_from_contract'],None)
            self.assertEqual(first['resource_requirements']['clarification_questions'][0]['id'],'dataset_source')
            session['versions'][0]['contract']['acceptance']['threshold']=90
            self.assertNotEqual(first['plan_id'],plan(session,root)['plan_id'])
        self.assertEqual(original['versions'][0]['contract']['acceptance']['threshold'],80)

    def test_budget_shape_is_checked_before_resource_extraction(self):
        for budget in (10,0,True,'10',[10]):
            with self.subTest(budget=budget):
                result=configured_resources({'budget':budget})
                self.assertIsNone(result['gpu_budget_from_contract'])
                self.assertIn('budget_issue',result)
        for budget,expected in ((None,None),({},None),({'gpu_hours':10},10)):
            result=configured_resources({'budget':budget})
            self.assertEqual(result['gpu_budget_from_contract'],expected)
            self.assertNotIn('budget_issue',result)

    def test_accuracy_units_and_complete_coverage(self):
        truth=[{'sample_id':'1','label':'cat'},{'sample_id':'2','label':'dog'}]
        predictions=[{'sample_id':'1','label':'cat','confidence':.9},{'sample_id':'2','label':'cat','confidence':.7}]
        report=evaluate(truth,predictions,['cat','dog'],80,'percent')
        self.assertEqual(report['value'],50)
        self.assertFalse(report['passed'])
        self.assertEqual(evaluate(truth,predictions,['cat','dog'],.4,'fraction')['value'],.5)
        for invalid in (predictions[:1],predictions+[predictions[0]],
                        [dict(predictions[0],confidence=float('nan')),predictions[1]],
                        [dict(predictions[0],label='unknown'),predictions[1]]):
            with self.assertRaises(ValueError):evaluate(truth,invalid,['cat','dog'],80,'percent')
        with self.assertRaises(ValueError):evaluate(truth,predictions,['cat','dog'],80,'fraction')


if __name__=='__main__':unittest.main()
