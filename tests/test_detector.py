import json
from pathlib import Path
import tempfile
import unittest
from vision_rsi.detector import COCO_IDS, detections, dataset_check

class DetectorTests(unittest.TestCase):
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
