"""Frozen development metric evaluation of isolated candidate adapters."""
import hashlib
import json
from pathlib import Path

from .event_eval import PROTOCOL, evaluate as evaluate_events, read_document
from .runner import atomic_json,digest


def evaluate(store,candidate_id,remote,module,function,contract_path,dataset_path,expected_contract_sha256=None,expected_dataset_sha256=None):
    contract_raw,contract=read_document(contract_path,512*1024)
    dataset_raw,dataset=read_document(dataset_path,2*1024*1024)
    if expected_contract_sha256 is not None and hashlib.sha256(contract_raw).hexdigest()!=expected_contract_sha256:
        raise ValueError('Frozen research contract changed before evaluation')
    if expected_dataset_sha256 is not None and hashlib.sha256(dataset_raw).hexdigest()!=expected_dataset_sha256:
        raise ValueError('Frozen validation dataset changed before evaluation')
    if not isinstance(contract,dict) or not isinstance(contract.get('acceptance'),dict) or contract['acceptance'].get('evaluation_protocol')!=PROTOCOL:
        raise ValueError('Adapter metric evaluation currently requires the fixed event_micro_f1 protocol')
    if not isinstance(dataset,dict) or set(dataset)!={'purpose','samples','ground_truth'} or dataset['purpose']!='development_validation':
        raise ValueError('Dataset must explicitly be development_validation, with samples and ground_truth; no hidden-test feedback')
    samples=dataset['samples'];truth=dataset['ground_truth']
    if not isinstance(samples,list) or not 1<=len(samples)<=16:raise ValueError('Require 1..16 frozen validation samples')
    ids=[sample.get('sample_id') for sample in samples if isinstance(sample,dict)]
    if len(ids)!=len(samples) or any(not isinstance(value,str) or not value for value in ids) or len(set(ids))!=len(ids):
        raise ValueError('Validation input IDs must be unique nonempty strings')
    if not isinstance(truth,dict) or not isinstance(truth.get('samples'),list) or not all(isinstance(row,dict) for row in truth['samples']):raise ValueError('Missing validation ground truth samples')
    if {row.get('sample_id') for row in truth['samples']}!=set(ids):raise ValueError('Ground truth coverage differs from frozen inputs')
    evaluator_sha=hashlib.sha256(Path(__file__).with_name('event_eval.py').read_bytes()).hexdigest()
    identity={'candidate_id':candidate_id,'module':module,'function':function,
              'contract_sha256':hashlib.sha256(contract_raw).hexdigest(),'dataset_sha256':hashlib.sha256(dataset_raw).hexdigest(),
              'evaluator_sha256':evaluator_sha,'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    evaluation_id=digest(identity)
    # Validate identities and fixed source before using a cached runtime result.
    if not isinstance(candidate_id,str) or len(candidate_id)!=64 or any(c not in '0123456789abcdef' for c in candidate_id):
        raise ValueError('Invalid candidate ID')
    candidate=store.verify(json.loads((store.root/candidate_id/'candidate.json').read_text(encoding='utf-8')))
    folder=store.root/candidate_id/'evaluations'/evaluation_id
    folder.mkdir(parents=True,exist_ok=True)
    for name,raw in (('contract.json',contract_raw),('dataset.json',dataset_raw)):
        path=folder/name
        if path.exists() and path.read_bytes()!=raw:raise ValueError('Frozen evaluation input changed')
        if not path.exists():path.write_bytes(raw)
    gt_path=folder/'ground-truth.json';atomic_json(gt_path,truth)
    # Use the same evaluator to validate labels, schema, workload and thresholds before remote execution.
    evaluate_events(gt_path,gt_path,contract_path=folder/'contract.json')
    checked=store.check_adapter(candidate_id,remote,module,function,contract,samples,check_id=evaluation_id[:32])
    report={'evaluation_id':evaluation_id,'identity':identity,'git_revision':candidate['git_revision'],
            'candidate_id':candidate_id,'purpose':'development_validation','sample_count':len(samples),
            'adapter_report_path':checked['adapter_report_path'],'status':'adapter_failed',
            'acceptance_evaluated':False,'metric_report':None,'quality_verified':False,
            'capability_registered':False,'agent_adopted':False,'gpu_used':False,
            'scope':'Frozen development metric only; dataset provenance/independence and production quality are not verified. No hidden test, registration or RSI adoption.'}
    if checked['status']=='adapter_contract_passed':
        outputs=checked['response']['observation']['results']
        predictions={'labels':truth['labels'],'samples':[{'sample_id':sample_id,'events':value['events']} for sample_id,value in zip(ids,outputs)]}
        pred_path=folder/'predictions.json';atomic_json(pred_path,predictions)
        metric=evaluate_events(gt_path,pred_path,contract_path=folder/'contract.json')
        report.update(acceptance_evaluated=True,metric_report=metric,
                      status='development_metric_met' if metric['metric_threshold_met'] else 'development_metric_not_met')
    path=folder/'evaluation.json';atomic_json(path,report)
    return dict(report,report_path=str(path.resolve()))
