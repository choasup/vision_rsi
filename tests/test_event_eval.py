import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.event_eval import PROTOCOL, evaluate, matched_count, read_document


def event(start, end, label='action'):
    return {'label': label, 'start_seconds': start, 'end_seconds': end}


class EventEvaluationTests(unittest.TestCase):
    def test_bounded_json_rejects_duplicates_nonfinite_depth_and_size(self):
        path=self.root/'bounded.json'
        for raw,fragment in [(b'{"labels":[],"labels":[]}', 'Duplicate'),
                             (b'{"value":NaN}','Nonfinite'),
                             (b'['*66+b'0'+b']'*66,'nesting')]:
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,fragment):read_document(path,1024)
        path.write_bytes(b'[] ')
        with self.assertRaisesRegex(ValueError,'byte limit'):read_document(path,2)
        path.write_bytes(b'[]')
        self.assertEqual(read_document(path,2),(b'[]',[]))

    def test_workload_limits_reject_before_matching(self):
        gt=self.write('gt.json',[event(0,1),event(1,2)])
        pred=self.write('pred.json',[event(0,1),event(1,2)])
        with patch('vision_rsi.event_eval.matched_count') as matching:
            with patch('vision_rsi.event_eval.MAX_COMPARISON_PAIRS',3):
                with self.assertRaisesRegex(ValueError,'workload'):evaluate(gt,pred)
            with patch('vision_rsi.event_eval.MAX_TOTAL_EVENTS',1):
                with self.assertRaisesRegex(ValueError,'Event count'):evaluate(gt,pred)
            matching.assert_not_called()
        self.assertEqual(evaluate(gt,pred)['comparison_pairs'],4)

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
        analysis=report['error_analysis']
        self.assertEqual(analysis['failing_label_count'],1)
        self.assertEqual(analysis['failing_sample_count'],1)
        self.assertEqual(analysis['worst_labels'][0]['fn'],1)
        self.assertEqual(analysis['worst_samples'][0]['fp'],2)
        self.assertNotIn('start_seconds',json.dumps(analysis))

    def test_error_attribution_distinguishes_labels_and_is_order_independent(self):
        docs=[{'labels':['action','other'],'samples':[{'sample_id':'clip1','events':items}]} for items in
              ([event(0,1),event(2,3,'other')],[event(0,1),event(0,1),event(5,6,'other')])]
        paths=[self.root/'gt.json',self.root/'pred.json']
        for path,doc in zip(paths,docs):path.write_text(json.dumps(doc),encoding='utf-8')
        report=evaluate(*paths)
        self.assertEqual((report['tp'],report['fp'],report['fn']),(1,2,1))
        rows={row['label_excerpt']:row for row in report['error_analysis']['worst_labels']}
        self.assertEqual((rows['action']['tp'],rows['action']['fp'],rows['action']['fn']),(1,1,0))
        self.assertEqual((rows['other']['tp'],rows['other']['fp'],rows['other']['fn']),(0,1,1))
        for path,doc in zip(paths,docs):
            doc['samples'][0]['events'].reverse();path.write_text(json.dumps(doc),encoding='utf-8')
        self.assertEqual(evaluate(*paths)['error_analysis'],report['error_analysis'])

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

    def contract(self):
        return {'acceptance': {'metric': 'event_micro_f1', 'direction': 'maximize',
                               'evaluation_protocol': PROTOCOL, 'iou_threshold': .75,
                               'threshold': .95},
                'output_schema': {'type': 'object', 'properties': {'events': {
                    'type': 'array', 'items': {'type': 'object', 'properties': {
                        'label': {'type': 'string', 'enum': ['action']},
                        'start_seconds': {'type': 'number'}, 'end_seconds': {'type': 'number'}},
                        'required': ['label', 'start_seconds', 'end_seconds']}}},
                    'required': ['events'], 'additionalProperties': False}}

    def test_task_binding_uses_frozen_thresholds(self):
        gt = self.write('gt.json', [event(0, 2)])
        pred = self.write('pred.json', [event(0, 1)])
        contract = self.root / 'contract.json'
        contract.write_text(json.dumps(self.contract()), encoding='utf-8')
        report = evaluate(gt, pred, contract_path=contract)
        self.assertTrue(report['contract_bound'])
        self.assertEqual(report['iou_threshold'], .75)
        self.assertEqual(report['threshold'], .95)
        self.assertEqual(report['tp'], 0)
        self.assertFalse(report['metric_threshold_met'])
        self.assertEqual(len(report['contract_sha256']), 64)
        for kwargs in ({'iou_threshold': .5}, {'threshold': .5}):
            with self.assertRaisesRegex(ValueError, 'override'):
                evaluate(gt, pred, contract_path=contract, **kwargs)

    def test_task_binding_rejects_wrong_protocol_and_output(self):
        gt = self.write('gt.json', [event(0, 1)])
        pred = self.write('pred.json', [event(0, 1)])
        path = self.root / 'contract.json'
        for field, value in [('metric', 'AP'), ('direction', 'minimize'),
                             ('evaluation_protocol', 'unspecified'), ('iou_threshold', None),
                             ('threshold', float('nan'))]:
            contract = self.contract()
            contract['acceptance'][field] = value
            path.write_text(json.dumps(contract), encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluate(gt, pred, contract_path=path)
        contract = self.contract()
        contract['output_schema']['properties']['events']['items']['properties']['label']['enum'] = ['other']
        path.write_text(json.dumps(contract), encoding='utf-8')
        with self.assertRaises(ValueError):
            evaluate(gt, pred, contract_path=path)
