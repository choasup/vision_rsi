"""Explicit local event micro-F1 protocol; no model or provenance claims."""
import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path

from .runner import atomic_json

PROTOCOL = 'vision-rsi/event_micro_f1/v1'


def number(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def samples(document, labels):
    if not isinstance(document, dict) or set(document) != {'labels', 'samples'}:
        raise ValueError('Document requires exactly labels and samples')
    if document['labels'] != labels:
        raise ValueError('Label vocabulary must match exactly, including order')
    rows = document['samples']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError('Require 1..10000 samples')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'sample_id', 'events'}:
            raise ValueError('Sample requires exactly sample_id and events')
        key, events = row['sample_id'], row['events']
        if not isinstance(key, str) or not key.strip() or key in result:
            raise ValueError('Sample IDs must be unique nonempty strings')
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError('At most 1000 events per sample')
        for event in events:
            if not isinstance(event, dict) or set(event) != {'label', 'start_seconds', 'end_seconds'}:
                raise ValueError('Event requires label, start_seconds, end_seconds')
            if not isinstance(event['label'], str) or event['label'] not in labels:
                raise ValueError('Unknown event label')
            start, end = event['start_seconds'], event['end_seconds']
            if not number(start, 0, float('inf')) or not number(end, 0, float('inf')) or end <= start:
                raise ValueError('Event times must be finite, nonnegative, end > start')
        result[key] = events
    return result


def matched_count(predicted, annotated, threshold):
    edges = []
    for p in predicted:
        adjacent = []
        for g, a in enumerate(annotated):
            if p['label'] != a['label']:
                continue
            intersection = max(0, min(p['end_seconds'], a['end_seconds']) - max(p['start_seconds'], a['start_seconds']))
            # Normalize first to avoid overflow for very large finite timestamps.
            scale = max(p['end_seconds'], a['end_seconds'])
            union = ((p['end_seconds'] - p['start_seconds']) / scale
                     + (a['end_seconds'] - a['start_seconds']) / scale - intersection / scale)
            if union > 0 and (intersection / scale) / union >= threshold:
                adjacent.append(g)
        edges.append(adjacent)
    pm, gm = {}, {}
    for root in range(len(predicted)):
        queue, seen, parent = deque([root]), {root}, {}
        free = None
        while queue and free is None:
            p = queue.popleft()
            for g in edges[p]:
                if g in parent:
                    continue
                parent[g] = p
                if g not in gm:
                    free = g
                    break
                if gm[g] not in seen:
                    seen.add(gm[g]); queue.append(gm[g])
        while free is not None:
            p = parent[free]
            previous = pm.get(p)
            pm[p], gm[free] = free, p
            free = previous
    return len(pm)


def evaluate(ground_truth, predictions, iou_threshold=None, threshold=None, contract_path=None):
    contract_hash = None
    contract = None
    if contract_path is not None:
        from .contracts import validate_schema_definition
        raw_contract = Path(contract_path).read_bytes()
        contract = json.loads(raw_contract)
        acceptance = contract.get('acceptance') if isinstance(contract, dict) else None
        if (not isinstance(acceptance, dict) or acceptance.get('metric') != 'event_micro_f1'
                or acceptance.get('direction') != 'maximize'
                or acceptance.get('evaluation_protocol') != PROTOCOL):
            raise ValueError('Contract must specify event_micro_f1/maximize and exact protocol')
        bound_iou, bound_threshold = acceptance.get('iou_threshold'), acceptance.get('threshold')
        if (not number(bound_iou, 0, 1) or bound_iou == 0
                or not number(bound_threshold, 0, 1)):
            raise ValueError('Contract requires explicit IoU and F1 thresholds')
        if ((iou_threshold is not None and iou_threshold != bound_iou)
                or (threshold is not None and threshold != bound_threshold)):
            raise ValueError('CLI thresholds cannot override the task contract')
        iou_threshold, threshold = bound_iou, bound_threshold
        schema = contract.get('output_schema')
        validate_schema_definition(schema)
        if schema.get('type') != 'object' or 'events' not in schema.get('properties', {}):
            raise ValueError('Contract output must define an events property')
        contract_hash = hashlib.sha256(raw_contract).hexdigest()
    iou_threshold = 0.5 if iou_threshold is None else iou_threshold
    threshold = 0.9 if threshold is None else threshold
    if not number(iou_threshold, 0, 1) or iou_threshold == 0 or not number(threshold, 0, 1):
        raise ValueError('Require 0 < IoU <= 1 and 0 <= F1 threshold <= 1')
    raw_gt, raw_pred = Path(ground_truth).read_bytes(), Path(predictions).read_bytes()
    gt_doc, pred_doc = json.loads(raw_gt), json.loads(raw_pred)
    labels = gt_doc.get('labels') if isinstance(gt_doc, dict) else None
    if (not isinstance(labels, list) or not labels or
            any(not isinstance(x, str) or not x.strip() for x in labels) or len(set(labels)) != len(labels)):
        raise ValueError('Require a unique nonempty label vocabulary')
    gt, pred = samples(gt_doc, labels), samples(pred_doc, labels)
    if contract is not None:
        from .contracts import validate_schema
        for events in pred.values():
            validate_schema(contract['output_schema'], {'events': events})
    if set(gt) != set(pred):
        raise ValueError('Prediction sample coverage must match exactly')
    positives = sum(map(len, gt.values()))
    if positives == 0:
        raise ValueError('Ground truth must contain at least one event')
    count = sum(map(len, pred.values()))
    tp = sum(matched_count(pred[key], gt[key], iou_threshold) for key in gt)
    precision, recall = tp / count if count else 0.0, tp / positives
    f1 = 2 * tp / (count + positives)
    return {'protocol': PROTOCOL, 'matching': 'maximum_cardinality/class_and_temporal_iou',
            'iou_threshold': iou_threshold, 'threshold': threshold, 'metric_scale': '0..1',
            'sample_count': len(gt), 'tp': tp, 'fp': count - tp, 'fn': positives - tp,
            'precision': precision, 'recall': recall, 'event_micro_f1': f1,
            'metric_threshold_met': f1 >= threshold, 'capability_registered': False,
            'provenance_verified': False, 'contract_bound': contract is not None,
            'contract_sha256': contract_hash,
            'ground_truth_sha256': hashlib.sha256(raw_gt).hexdigest(),
            'predictions_sha256': hashlib.sha256(raw_pred).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='vision-rsi evaluate-events')
    parser.add_argument('--ground-truth', required=True)
    parser.add_argument('--predictions', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--iou-threshold', type=float)
    parser.add_argument('--threshold', type=float)
    parser.add_argument('--contract', help='Bind exact task acceptance and output schema')
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.ground_truth, args.predictions, args.iou_threshold, args.threshold, args.contract)
        atomic_json(Path(args.output), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, OSError) as error:
        parser.exit(1, type(error).__name__ + ': ' + str(error) + '\n')
