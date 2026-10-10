"""One sealed event-metric holdout evaluation; no automatic production promotion."""
import base64
import hashlib
import json
from pathlib import Path

from .candidate_bundle import verify, run
from .campaign import lease
from .event_eval import read_document, evaluate
from .input_provenance import manifest, audit_manifest
from .runner import digest, atomic_json


def accept(bundle_path, dataset_path, development_paths, remote, output):
    bundle = verify(bundle_path)
    raw, data = read_document(dataset_path, 2*1024*1024)
    if not isinstance(data, dict) or set(data) != {'purpose', 'samples', 'ground_truth'} or data['purpose'] != 'independent_acceptance':
        raise ValueError('Require explicit independent_acceptance dataset; never hidden-test search feedback')
    samples = data['samples']; truth = data['ground_truth']
    if not isinstance(samples, list) or not 1 <= len(samples) <= 16:
        raise ValueError('Require 1..16 acceptance samples')
    ids = [row.get('sample_id') for row in samples if isinstance(row, dict)]
    if len(ids) != len(samples) or any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('Acceptance sample IDs must be unique')
    if not isinstance(truth, dict) or not isinstance(truth.get('samples'), list) or any(not isinstance(row, dict) for row in truth['samples']):
        raise ValueError('Ground truth samples required')
    if {row.get('sample_id') for row in truth['samples']} != set(ids):
        raise ValueError('Ground truth coverage differs')
    contract_bytes = base64.b64decode(bundle['contract_base64'])
    contract = json.loads(contract_bytes.decode('utf-8-sig'))
    cases = [{'sample': row} for row in samples]
    if bundle['identity'].get('media_transport') == 'vision_sample_transport_v1':
        from .media import package_sample
        cases = [dict(case, media=package_sample(contract, case['sample'], Path(dataset_path).resolve().parent, content_limit=512*1024)) for case in cases]
    rows = manifest(contract, cases)
    overlap = audit_manifest(development_paths, bundle['bundle_id'], bundle['identity']['contract_sha256'], rows)
    if overlap['status'] != 'no_overlap_in_supplied_records':
        raise ValueError('Acceptance inputs overlap development executions; no remote execution performed')
    binding = {'bundle_id': bundle['bundle_id'], 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
               'development_record_sha256': sorted(set(overlap['record_sha256'])), 'input_manifest': rows,
               'remote': remote, 'gate_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'evaluator_sha256': hashlib.sha256(Path(__file__).with_name('event_eval.py').read_bytes()).hexdigest(),
               'executor_sha256': hashlib.sha256(Path(__file__).with_name('candidate_bundle.py').read_bytes()).hexdigest(),
               'provenance_sha256': hashlib.sha256(Path(__file__).with_name('input_provenance.py').read_bytes()).hexdigest()}
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=True)
    with lease(root/'acceptance.lock', owner='Sealed bundle acceptance'):
        seal_path = root/'seal.json'; result_path = root/'acceptance.json'
        if seal_path.exists():
            _, seal = read_document(seal_path, 2*1024*1024)
            if seal != {'binding': binding, 'seal_sha256': digest(binding)}:
                raise ValueError('Acceptance slot is sealed; changing inputs, candidate or development history is forbidden')
        contract_path = root/'contract.json'; truth_path = root/'ground-truth.json'
        if contract_path.exists() and contract_path.read_bytes() != contract_bytes:
            raise ValueError('Frozen acceptance contract changed')
        contract_path.write_bytes(contract_bytes); atomic_json(truth_path, truth)
        evaluate(truth_path, truth_path, contract_path=contract_path)
        if not seal_path.exists():
            atomic_json(seal_path, {'binding': binding, 'seal_sha256': digest(binding)})
        if result_path.exists():
            _, saved = read_document(result_path, 2*1024*1024)
            if saved.get('seal_sha256') != digest(binding) or saved.get('report_sha256') != digest({k:v for k,v in saved.items() if k != 'report_sha256'}):
                raise ValueError('Acceptance report integrity differs')
            from .input_provenance import _read
            cached, cached_rows = _read(saved['execution_path'])
            if cached['record_sha256'] != saved['execution_record_sha256'] or cached_rows != rows or cached['binding'].get('bundle_id') != bundle['bundle_id']:
                raise ValueError('Acceptance execution evidence changed')
            return saved
        execution = run(bundle_path, samples, remote, root/'executions', bundle['bundle_id'], Path(dataset_path).resolve().parent, rows)
        predictions = {'labels': truth['labels'], 'samples': [{'sample_id': key, 'events': value['events']} for key,value in zip(ids, execution['outputs'])]}
        pred_path = root/'predictions.json'; atomic_json(pred_path, predictions)
        metric = evaluate(truth_path, pred_path, contract_path=contract_path)
        report = {'status': 'holdout_metric_met' if metric['metric_threshold_met'] else 'holdout_metric_not_met',
                  'seal_sha256': digest(binding), 'bundle_id': bundle['bundle_id'], 'metric_report': metric,
                  'execution_path': execution['execution_path'], 'execution_record_sha256': execution['record_sha256'],
                  'overlap_audit': overlap, 'quality_verified': False, 'production_accepted': False,
                  'complete_development_history_verified': False, 'capability_registered': False,
                  'limitations': 'Only supplied development records audited. No serving acceptance or automatic promotion. Never feed holdout results to research search.'}
        report['report_sha256'] = digest(report); atomic_json(result_path, report)
        return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='vision-rsi candidate-accept', description=__doc__)
    parser.add_argument('--bundle', required=True); parser.add_argument('--dataset', required=True)
    parser.add_argument('--development', required=True, action='append')
    parser.add_argument('--output', required=True, help='Single sealed acceptance slot; cannot be reused for different inputs')
    parser.add_argument('--config', default='config.local.json')
    args = parser.parse_args(argv)
    try:
        remote = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))['remote']
        print(json.dumps(accept(args.bundle,args.dataset,args.development,remote,args.output), ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
        parser.exit(1, str(error)+'\n')
