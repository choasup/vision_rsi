import json
from pathlib import Path
import tempfile
import unittest
import stat
from types import SimpleNamespace
from unittest.mock import patch
from vision_rsi.detector import COCO_IDS, detections, dataset_check, split_check

class DetectorTests(unittest.TestCase):
    def test_zero_area_training_annotations_are_recorded_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'annotations').mkdir()
            data={'categories':[{'id':i} for i in COCO_IDS],
                  'images':[{'id':1,'file_name':'one.jpg','width':10,'height':10}],
                  'annotations':[{'id':918,'image_id':1,'category_id':58,'bbox':[1,2,3,0]}]}
            for split in ('train','val'):
                (root/f'{split}2017').mkdir();(root/f'{split}2017/one.jpg').write_bytes(b'coverage-only')
                path=root/f'annotations/instances_{split}2017.json'
                raw=json.dumps(data);path.write_text(raw)
                result=split_check(root,split,1)
                self.assertEqual(path.read_text(),raw)
                if split=='train':
                    self.assertTrue(result['ready']);self.assertEqual(result['zero_area_annotation_ids'],[918])
                    self.assertEqual(result['annotations'],1)
                else:self.assertFalse(result['ready'])
            for bad in (-1,float('nan'),True):
                data['annotations'][0]['bbox'][3]=bad
                (root/'annotations/instances_train2017.json').write_text(json.dumps(data))
                self.assertFalse(split_check(root,'train',1)['ready'])

    def test_sparse_categories_and_box_protocol(self):
        self.assertEqual(len(set(COCO_IDS)),80)
        result=detections([[1,2,5,8],[0,0,2,2]],[90,12],[0.9,0.5])
        self.assertEqual(result,[{'bbox':[1,2,4,6],'category_id':90,'score':0.9}])
        with self.assertRaises(ValueError):detections([[1,2,0,8]],[1],[0.9])
        with self.assertRaises(ValueError):detections([[1,2,5,8]],[1],[float('nan')])
    def test_dataset_missing_and_wrong_categories(self):
        self.assertFalse(dataset_check('')['ready'])
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(dataset_check(root)['ready'])
            for name in ['train2017','val2017','annotations']:(Path(root)/name).mkdir()
            for split in ['train','val']:
                (Path(root)/'annotations'/f'instances_{split}2017.json').write_text(json.dumps({'images':[{'id':1}],'categories':[{'id':1}]}))
            self.assertFalse(dataset_check(root)['ready'])


    def test_split_requires_complete_image_and_annotation_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'annotations').mkdir();(root/'val2017').mkdir()
            path=root/'annotations/instances_val2017.json'
            image=root/'val2017/000000000001.jpg'
            data={'categories':[{'id':i} for i in COCO_IDS],
                  'images':[{'id':1,'file_name':image.name,'width':10,'height':10}],
                  'annotations':[{'id':1,'image_id':1,'category_id':90,'bbox':[0,0,2,2]}]}
            path.write_text(json.dumps(data))
            self.assertFalse(split_check(root,'val',1)['ready'])
            image.write_bytes(b'coverage-only-not-a-decoded-image')
            result=split_check(root,'val',1)
            self.assertTrue(result['ready']);self.assertFalse(result['pixel_decode_verified'])
            self.assertFalse(split_check(root,'val',5000)['ready'])
            self.assertFalse(dataset_check(root)['evaluation_ready'])
            for mode,attributes,size in ((stat.S_IFLNK,0,1),(stat.S_IFREG,1024,1),(stat.S_IFREG,0,0)):
                with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=mode,st_size=size,st_file_attributes=attributes)):
                    self.assertFalse(split_check(root,'val',1)['ready'])
            for mutation in ('missing_image','unknown_category','duplicate_annotation','duplicate_image','escape'):
                bad=json.loads(json.dumps(data))
                if mutation=='missing_image':bad['images'][0]['file_name']='missing.jpg'
                if mutation=='unknown_category':bad['annotations'][0]['category_id']=12
                if mutation=='duplicate_annotation':bad['annotations']*=2
                if mutation=='duplicate_image':bad['images']*=2
                if mutation=='escape':bad['images'][0]['file_name']='../escape.jpg'
                path.write_text(json.dumps(bad))
                self.assertFalse(split_check(root,'val',1)['ready'],mutation)
