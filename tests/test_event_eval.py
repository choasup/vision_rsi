import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from vision_rsi.event_eval import evaluate, matched_count


def event(start, end, label='action'):
    return {'label': label, 'start_seconds': start, 'end_seconds': end}


class EventEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, events, key='clip1'):
        path = self.root / name
        path.write_text(json.dumps({'labels': ['action'], 'samples': [
            {'sample_id': key, 'events': events}]}), encoding='utf-8')
        return path

    def test_augmenting_match_avoids_greedy_trap(self):
        gt = [event(0, 2), event(1, 3)]
        pred = [event(0, 3), event(0, 1)]
        for g in itertools.permutations(gt):
            for p in itertools.permutations(pred):
                self.assertEqual(matched_count(p, g, .5), 2)

    def test_counts_duplicates_and_missing_events(self):
        gt = self.write('gt.json', [event(0, 1), event(3, 4)])
        pred = self.write('pred.json', [event(0, 1), event(0, 1), event(6, 7)])
        report = evaluate(gt, pred)
        self.assertEqual((report['tp'], report['fp'], report['fn']), (1, 2, 1))
        self.assertEqual(report['event_micro_f1'], .4)
        self.assertFalse(report['capability_registered'])
        self.assertFalse(report['metric_threshold_met'])
        self.assertEqual(len(report['ground_truth_sha256']), 64)

    def test_empty_predictions_and_invalid_inputs(self):
        gt = self.write('gt.json', [event(0, 1)])
        pred = self.write('pred.json', [])
        self.assertEqual(evaluate(gt, pred)['event_micro_f1'], 0)
        for events in ([event(0, 0)], [event(True, 2)], [event(0, float('nan'))],
                       [event(0, 1, 'unknown')]):
            with self.assertRaises(ValueError):
                evaluate(gt, self.write('bad.json', events))
        with self.assertRaises(ValueError):
            evaluate(gt, self.write('other.json', [], 'other'))
        with self.assertRaises(ValueError):
            evaluate(self.write('empty.json', []), pred)
        for iou, threshold in [(0, .9), (.5, True), (.5, float('inf'))]:
            with self.assertRaises(ValueError):
                evaluate(gt, pred, iou, threshold)

    def test_cli_and_threshold_boundary(self):
        gt = self.write('gt.json', [event(0, 2)])
        pred = self.write('pred.json', [event(0, 1)])
        output = self.root / 'result.json'
        run = subprocess.run([sys.executable, '-m', 'vision_rsi', 'evaluate-events',
                              '--ground-truth', str(gt), '--predictions', str(pred),
                              '--output', str(output), '--threshold', '1'],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(output.read_text())['metric_threshold_met'])

    def test_label_and_overlap_constraints(self):
        self.assertEqual(matched_count([event(1, 2)], [event(0, 1)], .5), 0)
        self.assertEqual(matched_count([event(0, 1, 'other')], [event(0, 1)], .5), 0)
        self.assertEqual(matched_count([event(0, 1e308)], [event(0, 1e308)], 1), 1)
