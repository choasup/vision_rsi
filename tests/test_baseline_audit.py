import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.baseline_audit import audit
from vision_rsi.baseline_eval import cached_prediction
from vision_rsi.coco_eval import file_sha
from vision_rsi.detector import COCO_IDS


class AuditTests(unittest.TestCase):
    def test_real_cache_structure_identity_and_semantic_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'annotations').mkdir();(root/'val2017').mkdir();records=root/'records';records.mkdir()
            (root/'val2017/a.jpg').write_bytes(b'coverage-fixture')
            annotation=root/'annotations/instances_val2017.json'
            annotation.write_text(json.dumps({'categories':[{'id':i} for i in COCO_IDS],
                'images':[{'id':1,'file_name':'a.jpg','width':10,'height':10}],'annotations':[]}))
            path=records/'1.json';image_sha=file_sha(root/'val2017/a.jpg');ann_sha=file_sha(annotation)
            cached_prediction(path,'model',1,image_sha,lambda:[])
            before=path.read_bytes();result=audit(root,records,'model',ann_sha,1)
            self.assertEqual(result['audited_images'],1);self.assertFalse(result['quality_verified'])
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):audit(root,records,'other',ann_sha,1)
            for box,category,score in (([0,0,11,1],1,.5),([0,0,1,1],12,.5),([0,0,1,1],1,float('nan'))):
                path.unlink()
                cached_prediction(path,'model',1,image_sha,lambda:[{'bbox':box,'category_id':category,'score':score}])
                with self.assertRaises(ValueError):audit(root,records,'model',ann_sha,1)
            (root/'val2017/a.jpg').write_bytes(b'changed')
            with self.assertRaises(ValueError):audit(root,records,'model',ann_sha,1)
