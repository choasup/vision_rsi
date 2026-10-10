import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_coco_train import fixture_recipe
from vision_rsi.training_preflight import check
from vision_rsi.runner import digest


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.plan={'recipe':dict(fixture_recipe('.'),fixture=False,coco_root='/workspace/data',weights='/workspace/model.pth'),
                   'contract':{},'source_hashes':{'coco_train.py':'a'*64}}
        self.remote={'ssh_host':'fixture','workspace':'/workspace'}
        self.deployment={'directory':'/workspace/releases/'+'b'*64,'bundle_id':'b'*64}
        self.report={'status':'resources_verified','bundle_id':'b'*64,'recipe_sha256':digest(self.plan['recipe']),
                     'train_images':118287,'validation_images':5000,'gpu_used':False,'training_started':False}

    @patch('vision_rsi.training_preflight.subprocess.run')
    def test_valid_full_counts_are_bound_and_mismatches_rejected(self,run):
        run.return_value=SimpleNamespace(returncode=0,stdout=json.dumps(self.report),stderr='')
        result=check(self.remote,self.deployment,self.plan)
        self.assertEqual(len(result['validator_sha256']),64)
        self.assertEqual(run.call_args.kwargs['timeout'],100)
        for change in ({'train_images':1},{'gpu_used':True},{'recipe_sha256':'c'*64},{'bundle_id':'c'*64}):
            run.return_value.stdout=json.dumps(dict(self.report,**change))
            with self.assertRaises(ValueError):check(self.remote,self.deployment,self.plan)

    @patch('vision_rsi.training_preflight.subprocess.run')
    def test_remote_resource_error_is_not_training_success(self,run):
        run.return_value=SimpleNamespace(returncode=1,stdout='',stderr='Missing COCO image')
        with self.assertRaisesRegex(RuntimeError,'Missing COCO image'):check(self.remote,self.deployment,self.plan)
