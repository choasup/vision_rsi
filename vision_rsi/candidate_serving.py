"""Two fresh CPU serving contract checks, separate from model-quality approval."""
import hashlib
import math
from pathlib import Path
import time

from .campaign import lease
from .candidate_bundle import run
from .event_eval import read_document
from .input_provenance import _read
from .runner import atomic_json, digest
from .task_acceptance import pending_candidate, status


def _checked(path):
    _, value=read_document(path,4*1024*1024)
    if not isinstance(value,dict) or value.get('record_sha256')!=digest({k:v for k,v in value.items() if k!='record_sha256'}):
        raise ValueError('Serving evidence integrity differs')
    return value


def check(registry,session,version,dataset_path,remote,max_latency_seconds):
    if type(max_latency_seconds) not in (int,float) or not math.isfinite(max_latency_seconds) or not 0<max_latency_seconds<=120:
        raise ValueError('Specify an explicit finite end-to-end latency target in (0,120] seconds')
    max_latency_seconds=float(max_latency_seconds)
    name,artifact,task_binding,bundle=pending_candidate(registry,session,version)
    accepted=status(registry,name)
    if accepted['status']!='completed' or accepted['binding']['version']!=version or accepted['binding']['task_binding']!=task_binding:
        raise ValueError('Serving check requires completed acceptance for this candidate')
    _,report=read_document(accepted['report_path'],4*1024*1024)
    if report.get('report_sha256')!=accepted['report_sha256'] or report['report_sha256']!=digest({k:v for k,v in report.items() if k!='report_sha256'}):
        raise ValueError('Acceptance report integrity differs')
    if report.get('status')!='holdout_metric_met' or report.get('bundle_id')!=bundle['bundle_id']:
        raise ValueError('Frozen holdout metric must be met before serving checks')
    _,seal=read_document(Path(accepted['report_path']).with_name('seal.json'),4*1024*1024)
    if seal.get('seal_sha256')!=digest(seal['binding']) or seal['seal_sha256']!=report.get('seal_sha256'):
        raise ValueError('Acceptance seal identity differs')
    frozen=seal['binding']
    raw,data=read_document(dataset_path,2*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=frozen['dataset_sha256'] or frozen['remote']!=remote:
        raise ValueError('Serving inputs or remote differ from accepted endpoint')
    baseline,rows=_read(report['execution_path'])
    if baseline['record_sha256']!=report['execution_record_sha256'] or rows!=frozen['input_manifest'] or baseline['binding'].get('bundle_id')!=bundle['bundle_id']:
        raise ValueError('Accepted execution evidence differs')
    components={'executor_sha256':'candidate_bundle.py','validator_sha256':'contracts.py','provenance_sha256':'input_provenance.py',
                'runtime_driver_sha256':'candidate_runtime.py','transport_sha256':'remote.py'}
    for key,filename in components.items():
        if baseline['binding'].get(key)!=hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest():
            raise ValueError('Accepted serving implementation changed or identity missing: '+key)
    binding={'task_binding':task_binding,'version':version,'acceptance_report_sha256':report['report_sha256'],
             'bundle_id':bundle['bundle_id'],'max_latency_seconds':max_latency_seconds,
             'input_manifest':rows,'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    root=registry.root/name/'candidate-serving';root.mkdir(parents=True,exist_ok=True)
    with lease(root/'serving.lock',owner='Candidate serving checks'):
        seal_path=root/'binding.json'
        if seal_path.exists():
            _,saved=read_document(seal_path,4*1024*1024)
            if saved!=binding:raise ValueError('Serving slot frozen; target, candidate or evidence cannot change')
        else:atomic_json(seal_path,binding)
        trials=[]
        for index in range(2):
            trial_path=root/('trial-'+str(index)+'.json')
            if trial_path.exists():
                trial=_checked(trial_path)
                if trial['status']!='completed':raise RuntimeError('Serving measurement uncertain; not repeated automatically')
                execution,_=_read(trial['execution_path'])
                if trial.get('index')!=index or trial['binding_sha256']!=digest(binding) or execution['record_sha256']!=trial['execution_record_sha256'] or execution['input_manifest']!=rows or execution['binding'].get('bundle_id')!=bundle['bundle_id'] or execution['binding'].get('remote')!=remote:
                    raise ValueError('Serving trial identity differs')
                if not Path(trial['execution_path']).resolve().is_relative_to(root/('execution-'+str(index))):
                    raise ValueError('Serving trial execution directory differs')
            else:
                if (root/('execution-'+str(index))).exists():raise RuntimeError('Untracked serving execution retained; refusing fresh measurement claim')
                trial={'binding_sha256':digest(binding),'status':'reserved','index':index}
                trial['record_sha256']=digest(trial);atomic_json(trial_path,trial)
                started=time.perf_counter()
                execution=run(artifact/'bundle.json',data['samples'],remote,root/('execution-'+str(index)),bundle['bundle_id'],Path(dataset_path).resolve().parent,rows)
                elapsed=time.perf_counter()-started
                trial={'binding_sha256':digest(binding),'status':'completed','index':index,
                       'elapsed_seconds':elapsed,'execution_path':execution['execution_path'],
                       'execution_record_sha256':execution['record_sha256']}
                trial['record_sha256']=digest(trial);atomic_json(trial_path,trial)
            elapsed=trial['elapsed_seconds']
            if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<0:raise ValueError('Invalid serving latency evidence')
            trials.append(dict(trial,outputs_match_acceptance=execution['outputs']==baseline['outputs'],
                               latency_target_met=elapsed<=max_latency_seconds))
        passed=all(row['outputs_match_acceptance'] and row['latency_target_met'] for row in trials)
        result={'task_id':name,'version':version,'binding_sha256':digest(binding),
                'status':'serving_contract_checks_met' if passed else 'serving_contract_checks_not_met',
                'trials':trials,'fresh_execution_count':2,'latency_scope':'Entire supplied batch, including transport and decode',
                'environment_fully_verified':False,'quality_verified':False,'production_accepted':False,'capability_registered':False,
                'limitations':'Two observed CPU runs on accepted samples, not workload-wide latency, complete environment or model-quality certification.'}
        result['record_sha256']=digest(result)
        result_path=root/'serving.json'
        if result_path.exists() and _checked(result_path)!=result:raise ValueError('Saved serving report differs')
        if not result_path.exists():atomic_json(result_path,result)
        return result
