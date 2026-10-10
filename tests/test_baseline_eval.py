import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.baseline_eval import cached_prediction


class BaselineCacheTests(unittest.TestCase):
    def test_resume_reuses_known_output_and_rejects_changed_identity_input_or_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'1.json';calls=[]
            def predict():calls.append(1);return [{'bbox':[0,0,1,1],'category_id':1,'score':.5}]
            first=cached_prediction(path,'model-source',1,'image-sha',predict)
            self.assertEqual(cached_prediction(path,'model-source',1,'image-sha',predict),first)
            self.assertEqual(len(calls),1)
            for identity,image_id,image_sha in [('other-model',1,'image-sha'),('model-source',2,'image-sha'),('model-source',1,'changed')]:
                with self.assertRaises(ValueError):cached_prediction(path,identity,image_id,image_sha,predict)
            saved=json.loads(path.read_text());saved['detections']=[];path.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):cached_prediction(path,'model-source',1,'image-sha',predict)
