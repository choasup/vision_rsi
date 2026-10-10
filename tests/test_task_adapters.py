import copy
import unittest
from vision_rsi.task_adapters import training_adapter


class TaskAdapterTests(unittest.TestCase):
    def contract(self):
        return {'inputs':{'image':{'type':'image','required':True}},
                'acceptance':{'metric':'box_AP','direction':'maximize','evaluation_protocol':'COCO bbox AP'},
                'output_schema':{'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}}}

    def test_compatible_contract_is_not_a_training_or_quality_claim(self):
        contract=self.contract();before=copy.deepcopy(contract)
        result=training_adapter(contract)
        self.assertTrue(result['implementation_supported']);self.assertEqual(result['adapter_id'],'coco_detection_v1')
        self.assertFalse(result['training_performed']);self.assertFalse(result['model_quality_verified'])
        self.assertEqual(contract,before)

    def test_joint_video_metrics_and_output_incompatibility_stay_explicit(self):
        for kind in ('image_list','video','text'):
            contract=self.contract();contract['inputs']['image']['type']=kind
            result=training_adapter(contract)
            self.assertFalse(result['implementation_supported']);self.assertIsNone(result['adapter_id'])
        contract=self.contract();contract['acceptance']['metric']='F1'
        self.assertFalse(training_adapter(contract)['implementation_supported'])
        contract=self.contract();contract['output_schema']={'type':'array','items':{'type':'number'}}
        self.assertFalse(training_adapter(contract)['implementation_supported'])
