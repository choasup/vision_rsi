import base64
import copy
import hashlib
import json
import unittest
from vision_rsi.acceptance import review
from vision_rsi.runner import digest


def wrap(value):
    raw=json.dumps(value).encode()
    return {'base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}


def evidence(score=65,fixture=False):
    recipe={'acceptance_threshold':60,'val_annotations_sha256':'a'*64,'fixture':fixture}
    plan={'recipe':recipe,'contract':{'acceptance':{'threshold':60,'direction':'maximize'}},'source_hashes':{'coco_train.py':'b'*64}}
    accepted=not fixture and score>=60
    acceptance={'threshold':60,'direction':'maximize','eligible_for_coco_val2017':not fixture,'passed':accepted}
    evaluation={'protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100','pycocotools_version':'2.0.11',
                'metrics':{'box_AP':score},'image_count':2 if fixture else 5000,'coverage_complete':True,
                'annotation_sha256':'a'*64,'predictions_sha256':'d'*64,'coverage_sha256':'e'*64,'acceptance':acceptance}
    ev=wrap(evaluation)
    identity={'recipe':recipe,'sources':plan['source_hashes'],'image_contents_sha256':'1'*64}
    result={'status':'evaluated','step':1,'fixture':fixture,'identity':identity,'identity_hash':digest(identity),
            'checkpoint_sha256':'c'*64,'evaluation_sha256':ev['sha256'],'acceptance':acceptance}
    receipt={'reports':{'result.json':wrap(result),'evaluation.json':ev,'progress.json':wrap({'status':'evaluated'})},
             'artifact_hashes':{'checkpoint.pt':'c'*64,'predictions.json':'d'*64,'coverage.json':'e'*64}}
    return plan,receipt


class AcceptanceTests(unittest.TestCase):
    def test_matching_evidence_only_becomes_registration_candidate(self):
        plan,receipt=evidence()
        verdict=review(plan,receipt)
        self.assertTrue(verdict['passed']);self.assertEqual(verdict['status'],'ready_for_registration')
        self.assertFalse(verdict['capability_registered'])
    def test_fixture_and_low_score_never_validate_user_capability(self):
        for score,fixture in [(100,True),(20,False)]:
            plan,receipt=evidence(score,fixture)
            self.assertEqual(review(plan,receipt)['status'],'not_met')
    def test_changed_artifact_code_goal_and_missing_file_rejected(self):
        plan,receipt=evidence()
        for key in ('checkpoint.pt','predictions.json','coverage.json'):
            altered=copy.deepcopy(receipt);altered['artifact_hashes'][key]='f'*64
            with self.assertRaises(ValueError):review(plan,altered)
        for key,value in [('acceptance_threshold',50),('val_annotations_sha256','f'*64)]:
            altered=copy.deepcopy(plan);altered['recipe'][key]=value
            with self.assertRaises(ValueError):review(altered,receipt)
        altered=copy.deepcopy(plan);altered['source_hashes']['coco_train.py']='changed'
        with self.assertRaises(ValueError):review(altered,receipt)
        altered=copy.deepcopy(receipt);del altered['reports']['evaluation.json']
        with self.assertRaises(KeyError):review(plan,altered)
    def test_corrupt_report_is_rejected_before_acceptance(self):
        plan,receipt=evidence();receipt['reports']['result.json']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'report hash'):review(plan,receipt)
    def test_nan_metric_is_rejected_even_with_consistent_hashes(self):
        plan,receipt=evidence(float('nan'))
        with self.assertRaisesRegex(ValueError,'box_AP'):review(plan,receipt)
