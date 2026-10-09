import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from coco_rsi.runner import run


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path('config.example.json').read_text())

    @patch('coco_rsi.runner.revision', return_value='fixture-revision')
    def test_budget_resume_and_provenance(self, _):
        with tempfile.TemporaryDirectory() as folder:
            self.config['budget_gpu_hours'] = 2.5
            first = run(self.config, folder)
            self.assertEqual(len(first['experiments']), 2)
            self.assertEqual(first, run(self.config, folder))
            self.config['seed'] += 1
            with self.assertRaises(ValueError):
                run(self.config, folder)

    @patch('coco_rsi.runner.revision', return_value='fixture-revision')
    def test_zero_budget_and_real_execution_rejected(self, _):
        with tempfile.TemporaryDirectory() as folder:
            self.config['budget_gpu_hours'] = 0
            self.assertEqual(run(self.config, folder)['experiments'], [])
            self.config['mode'] = 'real'
            with self.assertRaises(ValueError):
                run(self.config, folder)
