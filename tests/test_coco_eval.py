import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.coco_eval import evaluate, file_sha


@unittest.skipUnless(importlib.util.find_spec('pycocotools'),'Install .[coco] for real evaluator integration tests')
class CocoEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.annotations=self.root/'annotations.json';self.predictions=self.root/'predictions.json';self.coverage=self.root/'coverage.json'
        self.annotations.write_text(json.dumps({'images':[{'id':1,'width':100,'height':100},{'id':2,'width':100,'height':100}],
            'categories':[{'id':1,'name':'object'}],
            'annotations':[{'id':i,'image_id':i,'category_id':1,'bbox':[10,10,20,20],'area':400,'iscrowd':0} for i in [1,2]]}))
        self.coverage.write_text('[1,2]')
        self.rows=[{'image_id':i,'category_id':1,'bbox':[10,10,20,20],'score':0.99} for i in [1,2]]
        self.predictions.write_text(json.dumps(self.rows))
    def run_eval(self):
        return evaluate(self.annotations,self.predictions,self.coverage,60,file_sha(self.annotations))
    def test_perfect_predictions_are_fixture_not_coco_acceptance(self):
        result=self.run_eval()
        self.assertAlmostEqual(result['metrics']['box_AP'],100)
        self.assertFalse(result['acceptance']['passed'])
        self.assertFalse(result['acceptance']['eligible_for_coco_val2017'])
    def test_no_detections_and_partial_predictions_include_all_images(self):
        self.predictions.write_text(json.dumps(self.rows[:1]))
        result=self.run_eval()
        self.assertLess(result['metrics']['box_AP'],60)
        self.predictions.write_text('[]')
        self.assertEqual(self.run_eval()['metrics']['box_AP'],0)
    def test_missing_coverage_or_changed_dataset_refused(self):
        self.coverage.write_text('[1]')
        with self.assertRaisesRegex(ValueError,'coverage'):self.run_eval()
        self.coverage.write_text('[1,2]')
        with self.assertRaisesRegex(ValueError,'hash'):
            evaluate(self.annotations,self.predictions,self.coverage,60,'0'*64)
    def test_invalid_prediction_refused(self):
        self.rows[0]['category_id']=12
        self.predictions.write_text(json.dumps(self.rows))
        with self.assertRaisesRegex(ValueError,'category'):self.run_eval()
