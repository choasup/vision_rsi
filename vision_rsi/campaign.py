"""Restartable Training control loop; policy code never executes tools directly."""
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path

from .runner import atomic_json,digest,revision
from .strategy_protocol import validate_decision
from .training_plan import prepare
from .training_runs import TrainingRuns,submit,observe,collect,TERMINAL,remote_identity

LOCAL_TERMINAL=TERMINAL|{'deployment_failed','resume_preflight_failed'}


@contextmanager
def lease(path):
    with path.open('a+b') as file:
        file.seek(0,2)
        if not file.tell():file.write(b'0');file.flush()
        file.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('Training controller is already active') from None
        else:
            import fcntl
            try:fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Training controller is already active') from None
        try:yield
        finally:
            if os.name=='nt':file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)


def available(state):
    if state.get('paused'):return []
    if not state.get('plan'):kinds=['prepare']
    elif state['plan']['status']=='blocked':return []
    elif not state.get('run_id'):kinds=['submit']
    elif state.get('run_status') not in LOCAL_TERMINAL:kinds=['observe','logs']
    elif state['run_status']=='completed' and not state.get('receipt_collected'):kinds=['collect']
    elif not state.get('analysis'):kinds=['analyze']
    else:return []
    sequence=len(state['history'])
    return [{'id':kind+'-'+str(sequence),'kind':kind,'estimated_cost':1,'expected_gain':2 if kind!='logs' else .5,'uncertainty':.1} for kind in kinds]


def choose(state,actions,steps_left,policy,remote):
    history=[{'id':row['action']['id'],'kind':row['action']['kind'],'status':row['status']} for row in state['history']]
    if policy:
        from .candidates import Candidates
        candidates=Candidates(policy['store'])
        try:
            check=candidates.check_strategy(policy['candidate_id'],remote,policy['module'],[{'history':history,'actions':actions,'budget':steps_left}])
        finally:candidates.close()
        if check['status']!='protocol_passed':raise ValueError('Experimental strategy failed protocol; no Training tool executed. See '+check['protocol_report_path'])
        decision=check['response']['observation']['results'][0]
        policy_evidence=check['protocol_report_path']
    else:
        decision={'action_id':actions[0]['id'],'rationale':'Deterministic baseline control order'}
        policy_evidence=None
    validate_decision(history,actions,steps_left,decision)
    return decision,policy_evidence


def execute(action,state,session,config,folder,runs):
    kind=action['kind'];remote=config['remote']
    if kind=='prepare':return prepare(session,config,folder/'plans')
    if kind=='submit':
        active=[row for row in runs.list(session['session_id']) if row['actual_gpu_hours'] is None]
        if active:
            matching=[row for row in active if row['plan_id']==state['plan']['plan_id'] and row['remote']==remote_identity(remote)]
            if len(active)==1 and matching:return matching[0]
            raise ValueError('Another active or uncertain Training attempt exists; reconcile it before submitting a new plan')
        return submit(state['plan'],remote,runs)
    if kind=='observe':return observe(state['run_id'],remote,runs)
    if kind=='logs':return observe(state['run_id'],remote,runs,'logs')
    if kind=='collect':return collect(state['run_id'],remote,runs)
    if kind=='analyze':
        record=runs.get(state['run_id']);verdict=record['details'].get('acceptance_review')
        analysis={'run_id':record['run_id'],'process_status':record['status'],'actual_gpu_hours':record['actual_gpu_hours'],
                  'acceptance_review':verdict,'quality_verified':bool(verdict and verdict.get('passed')),
                  'next_requirement':'Register and evaluate actual serving backend' if verdict and verdict.get('passed') else 'Investigate measured failure and propose a separately tracked experiment',
                  'method_or_agent_improvement_verified':False}
        if verdict and isinstance(verdict.get('box_AP'),(int,float)):
            analysis['metric_gap']=max(0,verdict['threshold']-verdict['box_AP'])
        return analysis
    raise ValueError('Unknown controller tool')


def project(state,action,result):
    kind=action['kind']
    if kind=='prepare':
        state['plan']=result;state['status']='blocked' if result['status']=='blocked' else 'ready'
        state['blockers']=result.get('blockers',[])
    elif kind in ('submit','observe','collect'):
        state['run_id']=result['run_id'];state['run_status']=result['status']
        state['status']='waiting' if result['status'] not in LOCAL_TERMINAL else 'processing_result'
        if kind=='collect':state['receipt_collected']=True
    elif kind=='analyze':
        state['analysis']=result
        state['status']='awaiting_serving_validation' if result['quality_verified'] else 'needs_research'


def advance(session,config,root='runs/campaigns',run_store='runs/training-runs',steps=3,policy=None,control=None):
    if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=10:raise ValueError('Controller steps must be 1..10')
    if not session['versions']:raise ValueError('Define the Training contract first')
    binding={'session_id':session['session_id'],'contract':session['versions'][-1]['contract'],
             'remote':remote_identity(config['remote']),'training':config.get('training',{}),
             'coco_root':config['remote'].get('coco_root'),'run_store':str(Path(run_store).resolve()),'policy':policy}
    control_sources={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.glob('*.py'))}
    campaign_id=digest(binding);folder=Path(root)/session['session_id']/campaign_id;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'state.json'
    with lease(folder/'controller.lock'):
        if path.exists():
            state=json.loads(path.read_text(encoding='utf-8'))
            if state['binding']!=binding:raise ValueError('Training controller binding changed')
        else:
            state={'campaign_id':campaign_id,'binding':binding,'session_id':session['session_id'],'task_id':session['task_id'],
                   'status':'new','history':[],'intent':None,'git_revision':revision(),'policy_adopted':False}
        if control:
            if control not in ('pause','resume','show'):raise ValueError('Unknown controller command')
            if control!='show':state['paused']=control=='pause';atomic_json(path,state)
            return dict(state,state_path=str(path.resolve()))
        runs=TrainingRuns(run_store)
        try:
            for index in range(steps):
                if state.get('paused'):break
                intent=state.get('intent')
                if intent is None:
                    actions=available(state)
                    if not actions:break
                    decision,evidence=choose(state,actions,steps-index,policy,config['remote'])
                    if decision['action_id'] is None:state['status']='policy_stopped';atomic_json(path,state);break
                    action=next(row for row in actions if row['id']==decision['action_id'])
                    intent={'action':action,'decision':decision,'policy_evidence':evidence,'status':'reserved',
                            'control_sources':control_sources,'git_revision':revision()}
                    state['intent']=intent;atomic_json(path,state)
                # Only fixed, idempotent tools may resume an interrupted intent.
                # submit reconciles the existing durable Training run ID.
                try:result=execute(intent['action'],state,session,config,folder,runs)
                except Exception as error:
                    state['status']='action_uncertain';state['last_error']=type(error).__name__+': '+str(error)
                    atomic_json(path,state);raise
                project(state,intent['action'],result)
                state['history'].append(dict(intent,status='completed',result=result))
                state['intent']=None;state.pop('last_error',None);atomic_json(path,state)
                if state['status'] in ('waiting','blocked'):break
        finally:runs.close()
    return dict(state,state_path=str(path.resolve()))
