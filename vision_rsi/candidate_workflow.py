"""Bounded, resumable task delivery without retrying uncertain execution."""
import hashlib
from pathlib import Path

from .campaign import lease
from .event_eval import read_document
from .runner import atomic_json,digest
from .task_acceptance import pending_candidate
from .research_history import accept
from .candidate_serving import check
from .candidate_delivery import promote


def deliver(registry,session,version,dataset_path,research_root,remote,max_latency_seconds):
    name,_,task_binding,_=pending_candidate(registry,session,version)
    raw,_=read_document(dataset_path,2*1024*1024)
    # Validate target before reserving any acceptance or dispatching a process.
    import math
    if type(max_latency_seconds) not in (int,float) or not math.isfinite(max_latency_seconds) or not 0<max_latency_seconds<=120:
        raise ValueError('Specify a finite latency target in (0,120] seconds')
    binding={'task_binding':task_binding,'version':version,'dataset_path':str(Path(dataset_path).resolve()),
             'dataset_sha256':hashlib.sha256(raw).hexdigest(),'research_root':str(Path(research_root).resolve()),
             'remote':remote,'max_latency_seconds':float(max_latency_seconds),
             'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    root=registry.root/name/'delivery-workflows'/version
    root.mkdir(parents=True,exist_ok=True)
    with lease(root/'workflow.lock',owner='Task delivery workflow'):
        path=root/'binding.json'
        if path.exists():
            _,saved=read_document(path,2*1024*1024)
            if saved!=binding:raise ValueError('Delivery workflow already bound to different requirements, inputs or target')
        else:atomic_json(path,binding)
        state={'task_id':name,'source_version':version,'binding_sha256':digest(binding),
               'completed_phases':[],'status':'running','production_accepted':False,
               'scope':'Scoped task delivery; no learned-model or whole-Agent launch guarantee.'}
        phase='acceptance'
        def save():
            state['record_sha256']=digest({k:v for k,v in state.items() if k!='record_sha256'})
            atomic_json(root/'state.json',state)
        save()
        try:
            # Each component validates its persisted evidence on every resume.
            # No generic retry loop, fresh acceptance slot or changed candidate.
            report=accept(registry,session,version,dataset_path,remote,research_root)
            state['completed_phases'].append('acceptance');save()
            if report['status']!='holdout_metric_met':
                state['status']='acceptance_not_met';save();return state
            phase='serving'
            report=check(registry,session,version,dataset_path,remote,max_latency_seconds)
            state['completed_phases'].append('serving');save()
            if report['status']!='serving_contract_checks_met':
                state['status']='serving_not_met';save();return state
            phase='promotion'
            delivery=promote(registry,session,version,research_root,remote)
            state['completed_phases'].append('promotion')
            state.update(status='scoped_delivery_ready_for_test',version=delivery['version'],
                         acceptance_scope=delivery['validation']['scope'])
            save();return state
        except (Exception,KeyboardInterrupt) as error:
            state.update(status='interrupted' if isinstance(error,KeyboardInterrupt) else 'stopped',
                         stopped_phase=phase,error_type=type(error).__name__)
            save();raise


def status(registry,session,version):
    """Inspect persisted scheduling evidence; never infer a process is alive."""
    name,_,binding,_=pending_candidate(registry,session,version)
    root=registry.root/name/'delivery-workflows'/version
    _,saved=read_document(root/'binding.json',2*1024*1024)
    if not isinstance(saved,dict) or saved.get('task_binding')!=binding or saved.get('version')!=version:
        raise ValueError('Delivery workflow belongs to different task requirements')
    _,state=read_document(root/'state.json',2*1024*1024)
    if not isinstance(state,dict) or state.get('binding_sha256')!=digest(saved) or state.get('record_sha256')!=digest({k:v for k,v in state.items() if k!='record_sha256'}):
        raise ValueError('Delivery workflow state integrity differs')
    if (state.get('task_id')!=name or state.get('source_version')!=version
            or state.get('status') not in ('running','stopped','interrupted','acceptance_not_met','serving_not_met','scoped_delivery_ready_for_test')
            or state.get('completed_phases') not in ([],['acceptance'],['acceptance','serving'],['acceptance','serving','promotion'])):
        raise ValueError('Invalid persisted delivery workflow state')
    return {'workflow':state,'read_only':True,'remote_called':False,'llm_called':False,
            'process_liveness_verified':False,'production_accepted':False,
            'scope':'Persisted workflow observation only; running state is not proof of a live process. Use release-status for current delivery evidence.'}
