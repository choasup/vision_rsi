import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from vision_rsi.coco_train import CocoImages, validate_recipe,validate_checkpoint_progress,shared_image_identity,validate_checkpoint_rng
from vision_rsi.detector import COCO_IDS


def fixture_recipe(root):
    return {'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','coco_root':str(Path(root).resolve()),
            'weights':str((Path(root)/'weights.pth').resolve()),'weights_sha256':'0'*64,
            'train_annotations_sha256':'0'*64,'val_annotations_sha256':'0'*64,
            'epochs':1,'batch_size_per_gpu':2,'seed':42,'checkpoint_steps':1,'world_size':1,
            'min_size':64,'max_size':64,'learning_rate':.001,'weight_decay':.0001,'fixture':True}


class CocoTrainingValidationTests(unittest.TestCase):
    def test_rng_inspection_restores_caller_state_even_when_saved_cpu_state_is_invalid(self):
        class Tensor:
            dtype='uint8';ndim=1;device=SimpleNamespace(type='cpu')
            def numel(self):return 1
        original=Tensor();saved=Tensor();calls=[]
        def set_state(value):
            calls.append(value)
            if value is saved:raise RuntimeError('Synthetic incompatible CPU RNG payload')
        torch=SimpleNamespace(Tensor=Tensor,uint8='uint8',get_rng_state=lambda:original,set_rng_state=set_state)
        with self.assertRaisesRegex(RuntimeError,'incompatible'):
            validate_checkpoint_rng({'rank_rng':[{'cpu':saved,'cuda':Tensor()}]},1,torch)
        self.assertIs(calls[-1],original)
        calls.clear()
        with self.assertRaisesRegex(ValueError,'byte tensors'):
            validate_checkpoint_rng({'rank_rng':[{'cpu':'not a tensor','cuda':Tensor()}]},1,torch)
        self.assertEqual(calls,[])

    @patch('vision_rsi.coco_train.file_sha',return_value='a'*64)
    def test_shared_image_identity_matches_single_rank_without_duplicate_reads(self,hash_file):
        datasets=[SimpleNamespace(root=Path('train2017'),images=[{'id':1,'file_name':'one.jpg'}]),
                  SimpleNamespace(root=Path('val2017'),images=[{'id':2,'file_name':'two.jpg'}])]
        class Broadcast:
            saved=None
            def broadcast_object_list(self,payload,src):
                if payload[0] is not None:self.saved=payload[0]
                else:payload[0]=self.saved
        dist=Broadcast()
        expected=shared_image_identity(datasets,0,1)
        hash_file.reset_mock()
        self.assertEqual(shared_image_identity(datasets,0,8,dist),expected)
        self.assertEqual(hash_file.call_count,2);hash_file.reset_mock()
        self.assertEqual(shared_image_identity(datasets,7,8,dist),expected)
        hash_file.assert_not_called()
        with patch('vision_rsi.coco_train.file_sha',side_effect=OSError('fixture')):
            with self.assertRaisesRegex(RuntimeError,'OSError'):shared_image_identity(datasets,0,8,dist)
        with self.assertRaisesRegex(RuntimeError,'OSError'):shared_image_identity(datasets,7,8,dist)

    def test_checkpoint_progress_matches_padded_eight_rank_batches_and_epoch_boundaries(self):
        recipe=dict(fixture_recipe('.'),world_size=8,epochs=3,batch_size_per_gpu=2)
        rng=[{'cpu':'opaque-test-state','cuda':'opaque-test-state'} for _ in range(8)]
        for epoch,cursor,step in ((0,0,0),(0,2,2),(1,1,3),(2,2,6),(3,0,6)):
            validate_checkpoint_progress({'epoch':epoch,'cursor':cursor,'step':step,'rank_rng':rng},17,recipe)
        original={'epoch':1,'cursor':1,'step':3,'rank_rng':rng}
        for changes in ({'cursor':True},{'epoch':-1},{'step':4},{'cursor':3},{'epoch':3,'cursor':1,'step':7},
                        {'rank_rng':rng[:-1]},{'rank_rng':[{}]*8}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_checkpoint_progress(dict(original,**changes),17,recipe)

    def test_remote_linux_paths_are_independent_of_windows_host(self):
        recipe=dict(fixture_recipe('.'),coco_root='/home/research/coco',weights='/home/research/weights/model.pth')
        validate_recipe(recipe,path_flavor='posix')
        for path in ('relative/coco','C:\\coco','/home/../coco'):
            with self.assertRaises(ValueError):validate_recipe(dict(recipe,coco_root=path),path_flavor='posix')
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
            data['annotations'][0]['bbox']=[1,2,3,0]
            path.write_text(json.dumps(data))
            checked=CocoImages(root,'train',True)
            self.assertEqual(checked.zero_area_annotation_ids,[1])
            self.assertEqual(len(checked),1)  # The image remains in the full split.
            for invalid in (-1,float('nan'),True):
                data['annotations'][0]['bbox'][3]=invalid
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError,'Invalid annotation bbox'):CocoImages(root,'train',True)
            data['annotations'][0]['bbox']=[1,2,3,4]
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
            recipe.update(coco_root='/remote/coco',weights='/remote/weights.pth')
            recipe['acceptance_threshold']=1
            result=prepare(session,{'training':recipe,'budget_gpu_hours':999},folder)
            self.assertEqual(result['recipe']['acceptance_threshold'],60)
            self.assertFalse(result['recipe']['fixture'])
            self.assertEqual(result['status'],'ready_to_submit')
            self.assertLess(result['scheduler']['timeout_seconds'],3600)
            for key in ('llm_calls','llm_tokens','wall_seconds','cpu_seconds','energy_kwh'):
                contract['budget']={'gpu_hours':1,key:0}
                result=prepare(session,{'training':recipe},folder)
                self.assertEqual(result['status'],'blocked')
                self.assertTrue(any('budget.'+key in reason for reason in result['blockers']))
                self.assertEqual(result['contract']['budget'][key],0)
            contract['budget']={}
            result=prepare(session,{'training':recipe,'budget_gpu_hours':999},folder)
            self.assertEqual(result['status'],'blocked')
            self.assertIsNone(result['scheduler']['gpu_hours_budget'])
            import copy
            original=copy.deepcopy(contract)
            for field,bad_values in (('budget',('not an object',[1],1,True)),
                                     ('inputs',(['image'],'image',1,True)),
                                     ('acceptance',(['AP'],'AP',1,True))):
                for malformed in bad_values:
                    broken=copy.deepcopy(original);broken[field]=malformed
                    broken_session=dict(session,versions=[{'version':1,'contract':broken}])
                    result=prepare(broken_session,{'training':recipe},folder)
                    self.assertEqual(result['status'],'blocked')
                    self.assertEqual(result['contract'],broken)
                    self.assertTrue(result['blockers'])
                    self.assertFalse(result['training_performed'])
                    if field=='budget':self.assertIsNone(result['scheduler']['gpu_hours_budget'])
                    self.assertEqual(result['plan_id'],prepare(broken_session,{'training':recipe},folder)['plan_id'])
            with self.assertRaisesRegex(ValueError,'contract must be an object'):
                prepare(dict(session,versions=[{'version':1,'contract':[]}]),{},folder)
            with self.assertRaisesRegex(ValueError,'remote config must be an object'):
                prepare(session,{'remote':['bad']},folder)


class CheckpointHashTests(unittest.TestCase):
    def test_changed_checkpoint_rejected_before_training_initialization(self):
        from unittest.mock import patch
        from vision_rsi.coco_train import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'checkpoint.pt').write_bytes(b'changed')
            recipe=root/'recipe.json';recipe.write_text('{}')
            with patch('vision_rsi.coco_train.run') as train:
                with self.assertRaisesRegex(ValueError,'changed after inspection'):
                    main(['--recipe',str(recipe),'--output',str(root),'--resume','--checkpoint-sha256','0'*64])
                train.assert_not_called()
