import unittest
from vision_rsi.research import Task, compare, propose, study


class ResearchTests(unittest.TestCase):
    def test_same_budget_unique_and_deterministic(self):
        self.assertEqual(compare(), compare())
        for pair in compare()['paired_runs']:
            for strategy in ('sequential', 'adaptive'):
                run = pair[strategy]
                self.assertEqual(run['spent_gpu_hours'], 4)
                self.assertEqual(len({r['id'] for r in run['experiments']}), 4)

    def test_feedback_changes_selection_and_direction(self):
        history = [{'recipe': {'learning_rate_scale': 1.0, 'augmentation_strength': 1.0}, 'metric_value': 1},
                   {'recipe': {'learning_rate_scale': 0.5, 'augmentation_strength': 1.0}, 'metric_value': 2}]
        self.assertNotEqual(propose(history, 'adaptive', Task()),
                            propose(history, 'adaptive', Task(direction='minimize')))

    def test_zero_and_exhaustion(self):
        self.assertIsNone(study('adaptive', 1, 0)['best_metric'])
        self.assertEqual(study('adaptive', 1, 100)['spent_gpu_hours'], 9)
        with self.assertRaises(ValueError):
            study('adaptive', 1, -1)
