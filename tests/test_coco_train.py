import json
from pathlib import Path
import tempfile
import unittest
from vision_rsi.coco_train import CocoImages, validate_recipe
from vision_rsi.detector import COCO_IDS


def fixture_recipe(root):
    return {'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','coco_root':str(Path(root).resolve()),
            'weights':str((Path(root)/'weights.pth').resolve()),'weights_sha256':'0'*64,
            'train_annotations_sha256':'0'*64,'val_annotations_sha256':'0'*64,
            'epochs':1,'batch_size_per_gpu':2,'seed':42,'checkpoint_steps':1,'world_size':1,
            'min_size':64,'max_size':64,'learning_rate':.001,'weight_decay':.0001,'fixture':True}


class CocoTrainingValidationTests(unittest.TestCase):
    def test_recipe_rejects_unpinned_or_invalid_training(self):
        recipe=fixture_recipe('.')
        validate_recipe(recipe)
        for values in [{'weights_sha256':'not-pinned'},{'world_size':9},{'epochs':True},
                       {'learning_rate':float('nan')},{'fixture':1},{'min_size':128,'max_size':64}]:
            with self.assertRaises(ValueError):validate_recipe(dict(recipe,**values))
    def test_dataset_does_not_silently_become_subset_or_escape_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'annotations').mkdir();(root/'train2017').mkdir()
            (root/'train2017/one.jpg').write_bytes(b'fixture-only')
            data={'categories':[{'id':i} for i in COCO_IDS],'images':[{'id':1,'file_name':'one.jpg','width':64,'height':64}],
                  'annotations':[{'id':1,'image_id':1,'category_id':90,'bbox':[1,2,3,4]}]}
            path=root/'annotations/instances_train2017.json';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'full COCO'):CocoImages(root,'train')
            self.assertEqual(len(CocoImages(root,'train',True)),1)
            data['images'][0]['file_name']='../escape.jpg';(root/'escape.jpg').write_bytes(b'fixture-only')
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'escaping'):CocoImages(root,'train',True)

class TrainingPlanTests(unittest.TestCase):
    def test_preserves_threshold_and_rejects_mock_budget_and_fixture(self):
        from vision_rsi.training_plan import prepare
        from unittest.mock import patch
        contract={'goal':'COCO detection','inputs':{'image':{'type':'image','required':True}},
                  'output_schema':{'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}},
                  'acceptance':{'metric':'box_AP','threshold':60,'direction':'maximize','evaluation_protocol':'COCO standard bbox AP'},
                  'budget':{'gpu_hours':1},'assumptions':[],'open_questions':[],
                  'example_input':{'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.jpg'}}},'example_output':{'detections':[]}}
        session={'task_id':'coco','session_id':'one','versions':[{'version':1,'contract':contract}]}
        with tempfile.TemporaryDirectory() as folder,patch('vision_rsi.training_plan.revision',return_value='fixed'):
            recipe=fixture_recipe(folder)
            recipe['acceptance_threshold']=1
            result=prepare(session,{'training':recipe,'budget_gpu_hours':999},folder)
            self.assertEqual(result['recipe']['acceptance_threshold'],60)
            self.assertFalse(result['recipe']['fixture'])
            self.assertEqual(result['status'],'ready_to_submit')
            self.assertLess(result['scheduler']['timeout_seconds'],3600)
            contract['budget']={}
            result=prepare(session,{'training':recipe,'budget_gpu_hours':999},folder)
            self.assertEqual(result['status'],'blocked')
            self.assertIsNone(result['scheduler']['gpu_hours_budget'])
