"""Account for media executions in one frozen, paused task research ledger."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

from .campaign import lease
from .event_eval import read_document
from .input_provenance import _read
from .ledger import Ledger
from .runner import atomic_json, digest
from .task_research import status


def inspect(session, root):
    current=status(session,root);folder=Path(current['directory'])
    with closing(sqlite3.connect((folder/'research.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN');events=Ledger._events(db)
    from .research_state import snapshot
    state=snapshot(events)
    if state['state']!='paused' or state['pending_actions'] or state['uncertain_requests'] or state['cached_responses']:
        raise ValueError('Research must be paused with no pending actions or unresolved planning responses')
    if events[0]['payload'].get('task_binding')!=current['task_binding']:
        raise ValueError('Research task binding changed')
    validation=[e['payload']['binding'] for e in events if e['payload'].get('record_type')=='validation_binding']
    if any(e['payload'].get('record_type')=='baseline_binding' for e in events):
        raise ValueError('Imported baseline input history is outside covered media execution provenance')
    if len(validation)!=1 or validation[0].get('candidate_bundle_execution',{}).get('media_input') is not True:
        raise ValueError('History coverage requires frozen media-bundle research validation')
    contract_hash=events[0]['payload']['frozen_contract_sha256']
    if validation[0].get('contract_sha256')!=contract_hash:raise ValueError('Validation contract differs')
    finished={e['payload']['action']:e for e in events if e['kind']=='result'}
    paths=[];receipts=[]
    for action in (e for e in events if e['kind']=='action'):
        tool=action['payload'].get('tool')
        if tool not in ('inspect_repository','read_source','read_candidate_source','remote_environment','synthesize','stage_candidate','evaluate_contract','check_candidate','check_contract','read_training_run'):
            raise ValueError('Uncovered research action tool')
        if action['key'] not in finished:raise ValueError('Unfinished research action')
        if tool in ('check_candidate','check_contract','read_training_run'):
            raise ValueError('Research contains input-consuming tools without covered execution provenance')
        if tool!='evaluate_contract':continue
        result=finished.get(action['key'])
        if result is None or result['payload'].get('status')!='completed':
            raise ValueError('Every evaluation action needs a completed, linked execution report')
        observation=result['payload']['observation'];path=Path(observation['report_path']).resolve()
        if not path.is_relative_to(folder):raise ValueError('Evaluation report escapes task research directory')
        raw,report=read_document(path,2*1024*1024)
        if hashlib.sha256(raw).hexdigest()!=observation['report_sha256'] or report.get('identity')!=observation.get('evaluation_identity'):
            raise ValueError('Research evaluation report identity differs')
        identity=report['identity']
        if identity.get('contract_sha256')!=contract_hash or identity.get('dataset_sha256')!=validation[0]['sha256']:
            raise ValueError('Evaluation differs from frozen research data or contract')
        if report.get('status') not in ('development_metric_met','development_metric_not_met'):
            raise ValueError('Not a development evaluation report')
        execution_path=Path(report['execution_path']).resolve()
        if not execution_path.is_relative_to(folder):raise ValueError('Execution escapes research directory')
        execution,_=_read(execution_path)
        if execution['record_sha256']!=identity.get('execution_record_sha256') or execution['binding'].get('bundle_id')!=identity.get('bundle_id') or execution['binding'].get('input_sha256')!=identity.get('input_set_sha256'):
            raise ValueError('Evaluation execution identity differs')
        if execution.get('runtime_identity_sha256')!=identity.get('runtime_identity_sha256'):
            raise ValueError('Evaluation runtime identity differs')
        paths.append(str(execution_path))
        receipts.append({'action':action['key'],'report_sha256':observation['report_sha256'],'execution_record_sha256':execution['record_sha256']})
    if not paths:raise ValueError('No covered development evaluations in research ledger')
    # Orphaned reservations/results cannot silently disappear from the history audit.
    actual={str(p.resolve()) for p in (folder/'bundle-evaluations').rglob('execution.json')}
    if actual!=set(paths):raise ValueError('Unlinked execution records exist or linked records are outside evaluation store')
    identity={'task_binding':current['task_binding'],'events_sha256':digest(events),'event_count':len(events),
              'evaluation_receipts':receipts,'history_gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return {'identity':identity,'history_sha256':digest(identity),'development_paths':sorted(set(paths)),
            'ledger_history_verified':True,'scope':'selected_task_research_ledger',
            'complete_development_history_verified':False}


def accept(registry,session,version,dataset_path,remote,root):
    folder=Path(root).resolve()/session['session_id']
    if not (folder/'research.sqlite3').is_file():raise ValueError('Task research ledger missing')
    with lease(folder/'controller.lock',owner='Research acceptance seal'):
        with lease(folder/'research-control.lock',owner='Research acceptance seal'):
            history=inspect(session,root)
            def seal():
                if inspect(session,root)!=history:raise ValueError('Research history changed before acceptance')
                path=folder/'acceptance-history.json'
                if path.exists():
                    _,saved=read_document(path,2*1024*1024)
                    if saved!=history:raise ValueError('Sealed research history changed')
                else:atomic_json(path,history)
            from .task_acceptance import accept as task_accept
            report=task_accept(registry,session,version,dataset_path,history['development_paths'],remote,
                               research_history=history,before_dispatch=seal)
            return dict(report,research_history=history)
