"""Bind general research to an accepted training task without changing it."""
import hashlib
import json
from pathlib import Path
from .campaign import lease
from .contracts import issues
from .controller import research_step
from .ledger import Ledger
from .observatory import dashboard
from .runner import digest


def status(session, root='runs/task-research'):
    """Read the bound research database without creating or modifying it."""
    import re
    import sqlite3
    from contextlib import closing
    from .research_state import snapshot
    session_id=session['session_id']
    if not isinstance(session_id,str) or not re.fullmatch('[0-9a-f]{32}',session_id):
        raise ValueError('Invalid session ID')
    folder=Path(root).resolve()/session_id
    path=folder/'research.sqlite3'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        events=Ledger._events(db)
    if not events:raise ValueError('Research objective missing')
    binding=events[0]['payload'].get('task_binding')
    expected={'session_id':session_id,'task_id':session['task_id'],'contract_version':len(session['versions']),
              'contract_sha256':digest(session['versions'][-1]['contract']),'requirements_sha256':digest(session['turns'])}
    if binding!=expected:raise ValueError('Task changed since research binding; inspect the original research ledger')
    contract_path=folder/'contract.json'
    if hashlib.sha256(contract_path.read_bytes()).hexdigest()!=events[0]['payload']['frozen_contract_sha256']:
        raise ValueError('Frozen research contract hash mismatch')
    return {'directory':str(folder),'task_binding':binding,'research_status':snapshot(events),
            'events':len(events),'read_only':True}


def control(session, action, root='runs/task-research'):
    """Persist scheduling intent, without cancelling in-flight work or resetting quotas."""
    if action not in ('pause','resume'):raise ValueError('Unknown research control')
    current=status(session,root)
    folder=Path(current['directory'])
    # Separate short lock: a pause can be recorded while a bounded tool/API call runs.
    with lease(folder/'research-control.lock',owner='Research scheduling control'):
        if action=='resume' and (folder/'acceptance-history.json').exists():
            raise ValueError('Research history sealed for acceptance; cannot resume search')
        if action=='resume' and (folder/'candidate-selection.json').exists():
            raise ValueError('Development candidate selection sealed; cannot resume search')
        current=status(session,root)
        ledger=Ledger(folder)
        controls=[e for e in ledger.events() if e['kind'] in ('paused','resumed')]
        paused=bool(controls and controls[-1]['kind']=='paused')
        desired=action=='pause'
        changed=paused!=desired
        if changed:
            key='research-control-'+str(len(controls)+1)
            ledger.append(key,'paused' if desired else 'resumed',{
                'summary':'通用研究已暂停；不取消已在执行的调用。' if desired else '通用研究已恢复；保留原额度与未决记录。',
                'origin':'explicit_cli_control'})
        result=status(session,root)
        return dict(result,read_only=False,control_changed=changed,dashboard=dashboard(ledger),
                    in_flight_work_cancelled=False)


def prepare(session,root='runs/task-research'):
    if session.get('pending_request') or not session.get('versions'):
        raise ValueError('Resolve task requirements before starting research')
    latest=session['versions'][-1]
    if latest.get('review_required'):raise ValueError('Review task requirement changes before research')
    contract=latest['contract']
    blockers=[error for error in issues(contract) if '预算' not in error and not error.startswith('待澄清:')]
    if blockers:raise ValueError('Task interface is incomplete: '+'; '.join(blockers))
    session_id=session['session_id']
    import re
    if not isinstance(session_id,str) or not re.fullmatch('[0-9a-f]{32}',session_id):raise ValueError('Invalid session ID')
    folder=Path(root).resolve()/session_id
    folder.mkdir(parents=True,exist_ok=True)
    binding={'session_id':session_id,'task_id':session['task_id'],'contract_version':len(session['versions']),
             'contract_sha256':digest(contract),'requirements_sha256':digest(session['turns'])}
    raw=(json.dumps(contract,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n').encode('utf-8')
    path=folder/'contract.json'
    with lease(folder/'bootstrap.lock',owner='Task research bootstrap'):
        ledger=Ledger(folder)
        events=ledger.events()
        if events and events[0]['payload'].get('task_binding')!=binding:
            raise ValueError('Task changed since research binding; use a new research root, never overwrite the old objective')
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('Frozen research contract changed')
        else:
            if events:raise ValueError('Frozen research contract missing; not regenerated over existing research')
            temporary=path.with_suffix('.tmp');temporary.write_bytes(raw);temporary.replace(path)
        if not events:
            ledger.append('objective','objective',{'summary':contract['goal'],'task_binding':binding,
                'scope':'General research for the accepted training task; no automatic training or capability adoption',
                'contract_path':str(path),'frozen_contract_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        expected=ledger.events()[0]['payload']['frozen_contract_sha256']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Frozen research contract hash mismatch')
        return {'directory':str(folder),'dashboard':dashboard(ledger),'task_binding':binding,
                'task_contract':{'path':str(path),'sha256':expected},'gpu_used':False,'training_performed':False}


def advance(session,config,root='runs/task-research',steps=1,repository='.',task_context=None,training_runs=None):
    result=prepare(session,root)
    bound=dict(config,research=dict(config.get('research',{}),task_contract=result['task_contract']))
    if training_runs is not None:
        bound['_training_evidence_context']={'run_store':str(Path(training_runs).resolve()),'session_id':session['session_id']}
    if task_context is not None:
        if (task_context.get('session_id')!=session['session_id'] or task_context.get('task_id')!=session['task_id']
                or task_context.get('contract_version')!=session['versions'][-1].get('version')):
            raise ValueError('Task readiness does not match the frozen session version')
        bound['_task_readiness_context']=task_context
        result['training_readiness']=task_context
    return dict(result,execution=research_step(bound,result['directory'],steps=steps,repository=repository))
