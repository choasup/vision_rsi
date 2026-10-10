import copy
import unittest

from vision_rsi.serving_acceptance import review_serving


class ServingThresholdTests(unittest.TestCase):
    def setUp(self):
        self.manifest={'endpoint':{'contract':{'acceptance':{'threshold':60,'direction':'maximize'}},
            'checkpoint_sha256':'a'*64,'training_identity_hash':'b'*64,
            'recipe':{'val_annotations_sha256':'c'*64}},'artifacts':{'inference.py':'d'*64}}
        self.report={'backend':'cpu','protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100',
            'pycocotools_version':'2.0.11','checkpoint_sha256':'a'*64,'training_identity_hash':'b'*64,
            'inference_adapter_sha256':'d'*64,'annotation_sha256':'c'*64,'fixture':False,
            'image_count':5000,'coverage_complete':True,'metrics':{'box_AP':60},
            'predictions_sha256':'e'*64,'coverage_sha256':'f'*64}

    def test_malformed_threshold_never_promotes_even_with_complete_report(self):
        for value in (float('nan'),float('inf'),float('-inf'),True,False,-1,101,'60',None):
            manifest=copy.deepcopy(self.manifest)
            manifest['endpoint']['contract']['acceptance']['threshold']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'acceptance threshold'):
                review_serving(manifest,self.report)

    def test_original_threshold_is_enforced_at_boundary(self):
        self.assertTrue(review_serving(self.manifest,self.report)['passed'])
        self.report['metrics']['box_AP']=59.999
        with self.assertRaisesRegex(ValueError,'original task acceptance'):
            review_serving(self.manifest,self.report)
