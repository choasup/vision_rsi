"""Frozen local CPU baseline observations for planning, never acceptance."""
import hashlib
import math
from pathlib import Path
import re

from .detector import COCO_IDS
from .event_eval import read_document


def arguments(value):
    if not isinstance(value,dict) or set(value)!={'expected_receipt_sha256'} or not isinstance(value['expected_receipt_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['expected_receipt_sha256']):
        raise ValueError('read_baseline requires exactly expected_receipt_sha256')
    return value


def inspect(config,contract,expected_receipt_sha256=None):
    binding=config.get('research',{}).get('baseline_evidence')
    keys={'receipt','sha256','metrics','metrics_sha256','annotation_sha256'}
    if not isinstance(binding,dict) or set(binding)!=keys:raise ValueError('Explicit frozen baseline receipt/metrics paths and hashes required')
    for key in ('sha256','metrics_sha256','annotation_sha256'):
        if not isinstance(binding[key],str) or not re.fullmatch('[0-9a-f]{64}',binding[key]):raise ValueError('Invalid baseline evidence hash')
    if expected_receipt_sha256 is not None and arguments({'expected_receipt_sha256':expected_receipt_sha256})['expected_receipt_sha256']!=binding['sha256']:
        raise ValueError('Baseline receipt differs from planner snapshot')
    from .task_adapters import training_adapter
    if not training_adapter(contract)['implementation_supported']:raise ValueError('Baseline protocol is incompatible with this task contract')
    raw,receipt=read_document(binding['receipt'],1024*1024)
    metrics_raw,report=read_document(binding['metrics'],1024*1024)
    if hashlib.sha256(raw).hexdigest()!=binding['sha256'] or hashlib.sha256(metrics_raw).hexdigest()!=binding['metrics_sha256']:
        raise ValueError('Frozen baseline files changed')
    state=receipt['state']
    if receipt.get('report')!=report or state.get('metrics_sha256')!=binding['metrics_sha256']:
        raise ValueError('Baseline state and metric receipt differ')
    if (state.get('status')!='evaluated' or state.get('coco_evaluated') is not True or state.get('gpu_used') is not False
            or state.get('training_started') is not False or state.get('processed_images')!=5000 or state.get('total_images')!=5000
            or not isinstance(state.get('identity'),str) or not re.fullmatch('[0-9a-f]{64}',state['identity'])):
        raise ValueError('Completed full CPU baseline observation required')
    if (report.get('protocol')!='pycocotools.COCOeval/bbox/defaults' or report.get('pycocotools_version')!='2.0.11'
            or report.get('metric_scale')!='0..100' or report.get('coverage_complete') is not True or report.get('image_count')!=5000
            or report.get('annotation_sha256')!=binding['annotation_sha256'] or report.get('category_ids')!=list(COCO_IDS)):
        raise ValueError('Baseline evaluation protocol or data identity differs')
    for key in ('predictions_sha256','coverage_sha256'):
        if not isinstance(report.get(key),str) or not re.fullmatch('[0-9a-f]{64}',report[key]):raise ValueError('Baseline producer input/output identity missing')
    metrics={key:report['metrics'][key] for key in ('box_AP','AP50','AP75','AP_small','AP_medium','AP_large')}
    if any(type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100 for value in metrics.values()):raise ValueError('Invalid baseline metric')
    threshold=contract['acceptance']['threshold']
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=100:raise ValueError('Invalid task AP target')
    return {'kind':'collected_cpu_baseline','receipt_sha256':binding['sha256'],'metrics_sha256':binding['metrics_sha256'],
            'producer_identity':state['identity'],'protocol':report['protocol'],'metrics':metrics,'threshold':threshold,
            'metric_gap':threshold-metrics['box_AP'],'observed_metric_target_met':metrics['box_AP']>=threshold,
            'image_count':5000,'annotation_sha256':binding['annotation_sha256'],
            'predictions_sha256':report['predictions_sha256'],'coverage_sha256':report['coverage_sha256'],
            'quality_verified':False,'read_only':True,'remote_called':False,'training_performed':False,
            'scope':'Pinned locally collected producer evidence only; no re-evaluation of raw predictions, model ceiling proof, independent holdout, authenticity or capability approval.'}


def bind(ledger,config,contract=None,contract_sha256=None):
    saved=[event['payload']['binding'] for event in ledger.events() if event['payload'].get('record_type')=='baseline_binding']
    supplied=config.get('research',{}).get('baseline_evidence')
    if supplied is None:
        if saved:raise ValueError('Baseline evidence binding cannot be removed')
        return None
    observation=inspect(config,contract)
    binding=dict(supplied,receipt=str(Path(supplied['receipt']).resolve()),metrics=str(Path(supplied['metrics']).resolve()),contract_sha256=contract_sha256)
    if saved and (len(saved)!=1 or saved[0]!=binding):raise ValueError('Baseline evidence binding is frozen')
    if not saved:ledger.append('baseline-binding','evidence',{'summary':'Frozen local baseline evidence for planning; not acceptance',
        'record_type':'baseline_binding','binding':binding})
    return {'expected_receipt_sha256':observation['receipt_sha256'],'contract_sha256':contract_sha256,
            'scope':'Locally collected baseline; read_baseline to inspect measurements'}
