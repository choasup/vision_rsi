import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.capability import Capabilities


class CapabilityTests(unittest.TestCase):
    @patch('vision_rsi.capability.revision',return_value='fixture')
    def test_training_inference_and_integrity(self,_):
        with tempfile.TemporaryDirectory() as folder:
            registry=Capabilities(folder)
            try:
                trained=registry.train('examples/toy-task.json')
                self.assertEqual(trained['status'],'validated')
                self.assertEqual(trained['validation']['evaluations'],1)
                result=registry.infer('bright-object','examples/toy-input.json')
                self.assertEqual(result['output']['predictions'][0]['bbox'],[1,1,2,2])
                model=Path(folder)/'bright-object'/trained['version']/'model.json'
                model.write_text('{}')
                with self.assertRaises(ValueError): registry.infer('bright-object','examples/toy-input.json')
                blocked=registry.train('examples/coco-task.json')
                self.assertEqual(blocked['status'],'blocked')
                with self.assertRaises(ValueError): registry.infer('coco-detector','examples/toy-input.json')
            finally: registry.close()
