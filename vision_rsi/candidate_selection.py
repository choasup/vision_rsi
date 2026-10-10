"""Select from covered development executions, never holdout feedback."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile

from .campaign import lease
from .candidate_bundle import verify
from .event_eval import read_document,evaluate
from .input_provenance import _read,manifest
from .media import package_sample
from .research_history import inspect
from .runner import atomic_json,digest


def select(registry,session,research_root):
    folder=Path(research_root).resolve()/session['session_id']
    with lease(folder/'controller.lock',owner='Development candidate selection'):
        with lease(folder/'research-control.lock',owner='Development candidate selection'):
            history=inspect(session,research_root)
            target=folder/'candidate-selection.json'
            from .task_acceptance import status as acceptance_status
            if not target.exists() and acceptance_status(registry,session['task_id'])['status']!='not_reserved':
                raise ValueError('Select before reserving independent acceptance; post-holdout selection forbidden')
            from .ledger import Ledger
            events=Ledger(folder).events()
            binding=next(e['payload']['binding'] for e in events if e['payload'].get('record_type')=='validation_binding')
            raw,data=read_document(binding['path'],2*1024*1024)
            if hashlib.sha256(raw).hexdigest()!=binding['sha256'] or data.get('purpose')!='development_validation':
                raise ValueError('Frozen development data changed or purpose differs')
            results={e['payload']['action']:e['payload'] for e in events if e['kind']=='result'}
            options=[]
            for receipt in history['identity']['evaluation_receipts']:
                observation=results[receipt['action']]['observation']
                _,report=read_document(observation['report_path'],2*1024*1024)
                identity=report['identity'];bundle_id=identity['bundle_id']
                if not isinstance(bundle_id,str) or len(bundle_id)!=64 or any(c not in '0123456789abcdef' for c in bundle_id):
                    raise ValueError('Invalid evaluated bundle identity')
                path=folder/'bundles'/bundle_id/'bundle.json';bundle=verify(path)
                if bundle['bundle_id']!=bundle_id or bundle['identity']['contract_sha256']!=identity['contract_sha256']:
                    raise ValueError('Evaluated bundle or task contract differs')
                execution,rows=_read(report['execution_path'])
                contract=json.loads(base64.b64decode(bundle['contract_base64']))
                cases=[{'sample':sample,'media':package_sample(contract,sample,Path(binding['path']).resolve().parent,content_limit=512*1024)} for sample in data['samples']]
                if manifest(contract,cases)!=rows:raise ValueError('Development media changed since evaluation')
                if identity['evaluator_sha256']!=hashlib.sha256(Path(__file__).with_name('event_eval.py').read_bytes()).hexdigest():
                    raise ValueError('Development evaluator changed')
                truth=data['ground_truth']
                predictions={'labels':truth['labels'],'samples':[{'sample_id':sample['sample_id'],'events':output['events']}
                    for sample,output in zip(data['samples'],execution['outputs'])]}
                with tempfile.TemporaryDirectory(prefix='vision-rsi-selection-') as directory:
                    temporary=Path(directory)
                    (temporary/'contract.json').write_bytes(base64.b64decode(bundle['contract_base64']))
                    atomic_json(temporary/'truth.json',truth);atomic_json(temporary/'predictions.json',predictions)
                    metric=evaluate(temporary/'truth.json',temporary/'predictions.json',contract_path=temporary/'contract.json')
                if metric!=report['metric_report']:raise ValueError('Development metric differs from recomputed outputs')
                options.append({'action':receipt['action'],'bundle_id':bundle_id,'bundle_path':str(path),
                                'event_micro_f1':metric['event_micro_f1'],'threshold_met':metric['metric_threshold_met'],
                                'report_sha256':receipt['report_sha256'],'execution_record_sha256':execution['record_sha256']})
            ranked=sorted(options,key=lambda row:(-row['event_micro_f1'],row['bundle_id'],row['action']))
            if not ranked or not ranked[0]['threshold_met']:raise ValueError('No development candidate meets the frozen metric; continue development before independent acceptance')
            selection={'history_sha256':history['history_sha256'],'rule':'maximum_development_event_micro_f1_then_bundle_id_then_action',
                       'ranked':ranked,'selected':ranked[0],'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            if target.exists():
                _,saved=read_document(target,2*1024*1024)
                if saved['selection']!=selection:raise ValueError('Candidate selection already frozen against different development evidence')
            delivery=registry.register_candidate(session,ranked[0]['bundle_path'])
            result={'task_id':session['task_id'],'version':delivery['version'],'status':'selected_pending_independent_validation',
                    'selection':selection,'holdout_used':False,'quality_verified':False,'production_accepted':False}
            if target.exists():
                if saved!=result:raise ValueError('Saved candidate selection differs')
            else:atomic_json(target,result)
            return result
