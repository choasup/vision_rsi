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


def advance(session,config,root='runs/task-research',steps=1,repository='.',task_context=None):
    result=prepare(session,root)
    bound=dict(config,research=dict(config.get('research',{}),task_contract=result['task_contract']))
    if task_context is not None:
        if (task_context.get('session_id')!=session['session_id'] or task_context.get('task_id')!=session['task_id']
                or task_context.get('contract_version')!=session['versions'][-1].get('version')):
            raise ValueError('Task readiness does not match the frozen session version')
        bound['_task_readiness_context']=task_context
        result['training_readiness']=task_context
    return dict(result,execution=research_step(bound,result['directory'],steps=steps,repository=repository))
