"""Development event metrics for independently executable candidate bundles."""
import base64
import hashlib
import json
from pathlib import Path
from .candidate_bundle import verify,run
from .event_eval import read_document,evaluate
from .runner import atomic_json,digest


def evaluate_bundle(bundle_path,dataset_path,remote,output):
    bundle=verify(bundle_path)
    raw,data=read_document(dataset_path,2*1024*1024)
    if not isinstance(data,dict) or set(data)!={'purpose','samples','ground_truth'} or data['purpose']!='development_validation':
        raise ValueError('Require explicit development_validation samples and ground_truth; no hidden-test feedback')
    samples=data['samples'];truth=data['ground_truth']
    if not isinstance(samples,list) or not 1<=len(samples)<=16:raise ValueError('Require 1..16 validation samples')
    ids=[row.get('sample_id') for row in samples if isinstance(row,dict)]
    if len(ids)!=len(samples) or any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids):raise ValueError('Require unique sample IDs')
    if not isinstance(truth,dict) or not isinstance(truth.get('samples'),list) or any(not isinstance(row,dict) for row in truth['samples']):raise ValueError('Missing ground truth samples')
    if {row.get('sample_id') for row in truth['samples']}!=set(ids):raise ValueError('Ground truth coverage differs')
    binding={'bundle_id':bundle['bundle_id'],'dataset_sha256':hashlib.sha256(raw).hexdigest(),
             'evaluator_sha256':hashlib.sha256(Path(__file__).with_name('event_eval.py').read_bytes()).hexdigest(),
             'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    root=Path(output).resolve()/digest(binding);root.mkdir(parents=True,exist_ok=True)
    contract_path=root/'contract.json';contract_bytes=base64.b64decode(bundle['contract_base64'])
    if contract_path.exists() and contract_path.read_bytes()!=contract_bytes:raise ValueError('Frozen bundle evaluation contract changed')
    if not contract_path.exists():contract_path.write_bytes(contract_bytes)
    truth_path=root/'ground-truth.json';atomic_json(truth_path,truth)
    # Validate fixed labels, schema, protocol and thresholds before any transport.
    evaluate(truth_path,truth_path,contract_path=contract_path)
    execution=run(bundle_path,samples,remote,root/'executions',bundle['bundle_id'],Path(dataset_path).resolve().parent)
    identity=dict(binding,execution_record_sha256=execution['record_sha256'])
    folder=root/digest(identity);folder.mkdir(parents=True,exist_ok=True)
    predictions={'labels':truth['labels'],'samples':[{'sample_id':key,'events':value['events']}
        for key,value in zip(ids,execution['outputs'])]}
    pred_path=folder/'predictions.json';atomic_json(pred_path,predictions)
    metric=evaluate(truth_path,pred_path,contract_path=contract_path)
    report={'identity':identity,'status':'development_metric_met' if metric['metric_threshold_met'] else 'development_metric_not_met',
            'metric_report':metric,'execution_path':execution['execution_path'],'production_accepted':False,
            'quality_verified':False,'capability_registered':False,'agent_adopted':False,'gpu_used':False,
            'scope':'Development metric only; provenance, independent quality and production readiness unverified.'}
    path=folder/'evaluation.json';atomic_json(path,report)
    return dict(report,report_path=str(path))


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(prog='vision-rsi candidate-evaluate')
    parser.add_argument('--bundle',required=True);parser.add_argument('--dataset',required=True)
    parser.add_argument('--output',default='runs/bundle-evaluations');parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args(argv)
    try:
        remote=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))['remote']
        print(json.dumps(evaluate_bundle(args.bundle,args.dataset,remote,args.output),ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:parser.exit(1,str(error)+'\n')
