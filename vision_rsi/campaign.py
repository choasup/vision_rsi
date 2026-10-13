"""Restartable Training control loop; policy code never executes tools directly."""
from contextlib import contextmanager
import json
import math
import hashlib
import os
import re
import time
from pathlib import Path

from .runner import atomic_json,digest,revision
from .strategy_protocol import validate_decision
from .strategy_context import history_context,control_versions
from .training_plan import prepare
from .training_runs import TrainingRuns,submit,observe,collect,TERMINAL,remote_identity

LOCAL_TERMINAL=TERMINAL|{'deployment_failed','resume_preflight_failed'}


def list_campaigns(session_id,root='runs/campaigns'):
    if not isinstance(session_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',session_id):raise ValueError('Invalid session ID')
    rows=[]
    for path in sorted((Path(root)/session_id).glob('*/state.json')):
        state=json.loads(path.read_text(encoding='utf-8'))
        identity=state['campaign_id']
        if digest(state['binding'])!=identity or path.parent.name!=identity or state['binding']['session_id']!=session_id:
            raise ValueError('Stored campaign identity changed')
        policy=state['binding'].get('policy') or {}
        rows.append({'campaign_id':identity,'status':state['status'],'paused':state.get('paused',False),
                     'run_id':state.get('run_id'),'remote_status_last_observed':state.get('run_status'),
                     'research_rounds':state['binding'].get('research_rounds',0),'candidate_id':policy.get('candidate_id'),
                     'actions_recorded':len(state['history']),'state_path':str(path.resolve()),'live_remote_poll':False})
    return rows


@contextmanager
def lease(path,owner='Training controller'):
    with path.open('a+b') as file:
        file.seek(0,2)
        if not file.tell():file.write(b'0');file.flush()
        file.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError(owner+' is already active') from None
        else:
            import fcntl
            try:fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError(owner+' is already active') from None
        try:yield
        finally:
            if os.name=='nt':file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)


def available(state,memory=False):
    if state.get('paused') or state.get('policy_stop') or state.get('controller_budget_exhausted'):return []
    if not state.get('plan'):kinds=['prepare']
    elif state['plan']['status']=='blocked':return []
    elif not state.get('run_id'):kinds=['submit']
    elif state.get('run_status') not in LOCAL_TERMINAL:kinds=['observe','logs']
    elif state['run_status']=='completed' and not state.get('receipt_collected'):kinds=['collect']
    elif not state.get('analysis'):kinds=['analyze']
    elif not state['analysis']['quality_verified'] and state.get('receipt_collected') and not state.get('research_stopped') and state.get('proposals_attempted',0)<state.get('research_rounds',0):kinds=['propose_experiment']
    else:return []
    sequence=len(state['history'])
    actions=[{'id':kind+'-'+str(sequence),'kind':kind,'estimated_cost':1,'expected_gain':2 if kind!='logs' else .5,'uncertainty':.1} for kind in kinds]
    if memory:
        from .research_memory import memory_actions
        actions+=memory_actions(state['history'])
    return actions


def choose(state,actions,steps_left,policy,remote):
    attempted={row['action']['id'] for row in state['history']}
    if any(action['id'] in attempted for action in actions):
        raise ValueError('Controller action ID already appears in full history')
    history=history_context(state['history'])
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
    if kind=='retrieve_memory':
        from .research_memory import retrieve_page
        return retrieve_page(state['history'],action)
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
    if kind=='propose_experiment':
        from .experiments import propose_next
        record=runs.get(state['run_id'])
        request_id='experiment-'+state['campaign_id'][:24]+'-'+str(state.get('proposals_attempted',0))
        retry=state.get('intent',{}).get('explicit_retry',0)
        if retry:request_id+='-retry-'+str(retry)
        brief=(state.get('intent') or {}).get('decision',{}).get('research_brief')
        return propose_next(record,runs,config['llm'],folder/'experiments',request_id,research_brief=brief,
                            research_history=history_context(state.get('history',[])))
    if kind=='analyze':
        record=runs.get(state['run_id']);verdict=record['details'].get('acceptance_review')
        analysis={'run_id':record['run_id'],'process_status':record['status'],'actual_gpu_hours':record['actual_gpu_hours'],
                  'acceptance_review':verdict,'quality_verified':bool(verdict and verdict.get('passed')),
                  'next_requirement':'Register and evaluate actual serving backend' if verdict and verdict.get('passed') else 'Investigate measured failure and propose a separately tracked experiment',
                  'method_or_agent_improvement_verified':False}
        declared_budget=session['versions'][-1]['contract'].get('budget')
        budget=declared_budget.get('gpu_hours') if isinstance(declared_budget,dict) else None
        if not isinstance(budget,bool) and isinstance(budget,(int,float)) and math.isfinite(budget) and budget>0:
            remaining=budget if session['versions'][-1]['contract'].get('gpu_budget_scope')=='experiment' else runs.remaining(session['session_id'],budget)
            if isinstance(remaining,bool) or not isinstance(remaining,(int,float)) or not math.isfinite(remaining) or not 0<=remaining<=budget:
                raise ValueError('Invalid session GPU budget snapshot; analysis not persisted')
            analysis.update(authorized_gpu_hours=budget,remaining_gpu_hours=remaining)
        if verdict and isinstance(verdict.get('box_AP'),(int,float)):
            analysis['metric_gap']=max(0,verdict['threshold']-verdict['box_AP'])
        return analysis
    raise ValueError('Unknown controller tool')


def project(state,action,result):
    kind=action['kind']
    if kind=='prepare':
        state['plan']=result;state['status']='blocked' if result['status']=='blocked' else 'ready'
        state['blockers']=result.get('blockers',[])
    elif kind in ('submit','observe','logs','collect'):
        state['run_id']=result['run_id'];state['run_status']=result['status']
        state['status']='waiting' if result['status'] not in LOCAL_TERMINAL else 'processing_result'
        if kind=='collect':state['receipt_collected']=True
    elif kind=='analyze':
        state['analysis']=result
        state['status']='awaiting_serving_validation' if result['quality_verified'] else 'needs_research'
    elif kind=='propose_experiment':
        state['proposals_attempted']=state.get('proposals_attempted',0)+1
        if result['status']=='ready_to_submit':
            state['plan']=result;state['run_id']=None;state['run_status']=None;state['receipt_collected']=False;state['analysis']=None;state['status']='ready'
        else:
            state['status']=result['status']
            state['research_stopped']=result['status']=='budget_exhausted'


def campaign_binding(session,config,run_store,policy,research_rounds):
    binding={'session_id':session['session_id'],'contract':session['versions'][-1]['contract'],
             'remote':remote_identity(config['remote']),'training':config.get('training',{}),
             'coco_root':config['remote'].get('coco_root'),'run_store':str(Path(run_store).resolve()),'policy':policy,
             'research_rounds':research_rounds,'research_model':{key:config.get('llm',{}).get(key) for key in ('model','base_url')} if research_rounds else None}
    if research_rounds:
        for key in ('usage_ledger','usage_call_limit','thinking'):
            if key in config.get('llm',{}):binding['research_model'][key]=config['llm'][key]
    from .controller_budget import configured_limit
    limit=configured_limit(config)
    if limit is not None:binding['controller_tool_attempt_limit']=limit
    return binding


def advance(session,config,root='runs/campaigns',run_store='runs/training-runs',steps=3,policy=None,control=None,research_rounds=None,selected_campaign=None):
    if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=10:raise ValueError('Controller steps must be 1..10')
    saved_binding=None
    if selected_campaign:
        if not isinstance(selected_campaign,str) or not re.fullmatch('[0-9a-f]{64}',selected_campaign):raise ValueError('Invalid campaign ID')
        saved_path=Path(root)/session['session_id']/selected_campaign/'state.json'
        if not saved_path.is_file():raise ValueError('Unknown campaign for this Training session')
        saved=json.loads(saved_path.read_text(encoding='utf-8'));saved_binding=saved['binding']
        if digest(saved_binding)!=selected_campaign or saved['campaign_id']!=selected_campaign or saved_binding['session_id']!=session['session_id']:
            raise ValueError('Stored campaign identity changed')
        if research_rounds is not None and research_rounds!=saved_binding.get('research_rounds',0):raise ValueError('Selected campaign research limit cannot be overridden')
        if policy is not None and policy!=saved_binding.get('policy'):raise ValueError('Selected campaign policy cannot be overridden')
        research_rounds=saved_binding.get('research_rounds',0);policy=saved_binding.get('policy')
    if research_rounds is None:research_rounds=0
    if isinstance(research_rounds,bool) or not isinstance(research_rounds,int) or not 0<=research_rounds<=10:raise ValueError('Research rounds must be 0..10')
    if control not in ('show','pause') and session.get('pending_request'):
        raise ValueError('Resolve unprocessed task requirements before advancing Training')
    if not session['versions']:raise ValueError('Define the Training contract first')
    if not control and session['versions'][-1].get('review_required'):raise ValueError('Review pending requirements changes before advancing Training; active requirements have not been overwritten')
    binding=campaign_binding(session,config,run_store,policy,research_rounds)
    if saved_binding:
        comparable=dict(saved_binding)
        comparable.setdefault('research_rounds',0);comparable.setdefault('research_model',None)
        comparable.pop('control_sources',None)  # Legacy source snapshots remain in the immutable binding.
        if control not in ('show','pause') and binding!=comparable:raise ValueError('Current task/config differs from selected campaign; observe or pause it, but do not execute with changed requirements')
        binding=saved_binding
    control_sources={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.glob('*.py'))}
    campaign_id=digest(binding);folder=Path(root)/session['session_id']/campaign_id;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'state.json'
    with lease(folder/'controller.lock'):
        if path.exists():
            state=json.loads(path.read_text(encoding='utf-8'))
            if state['binding']!=binding:raise ValueError('Training controller binding changed')
        else:
            state={'campaign_id':campaign_id,'binding':binding,'session_id':session['session_id'],'task_id':session['task_id'],
                   'status':'new','history':[],'intent':None,'git_revision':revision(),'policy_adopted':False,'research_rounds':research_rounds}
        from .controller_budget import summary as control_budget
        try:budget_snapshot=control_budget(state)
        except ValueError as error:
            if control not in ('show','pause'):raise
            budget_snapshot={'valid':False,'error':str(error)}
        if control not in ('show','pause'):
            for row in state['history']:control_versions(row)
            if state.get('intent'):control_versions(state['intent'])
            if state.get('policy_stop'):control_versions(state['policy_stop'])
        if control:
            if control not in ('pause','resume','show'):raise ValueError('Unknown controller command')
            if control=='resume' and (state.get('intent') or {}).get('status')=='not_dispatched':
                intent=state['intent']
                intent['explicit_retry']=intent.get('explicit_retry',0)+1
                intent['status']='reserved'
                state['status']='retry_authorized'
            if control!='show':state['paused']=control=='pause';atomic_json(path,state)
            return dict(state,state_path=str(path.resolve()),controller_tool_budget=budget_snapshot)
        runs=TrainingRuns(run_store)
        try:
            for index in range(steps):
                if state.get('paused'):break
                budget_snapshot=control_budget(state)
                if budget_snapshot is not None and budget_snapshot['remaining_attempts']==0:
                    state.update(status='controller_budget_exhausted',controller_budget_exhausted=True)
                    atomic_json(path,state);break
                intent=state.get('intent')
                if intent is None:
                    actions=available(state,memory=True)
                    if not actions:break
                    choice_started=time.monotonic()
                    decision,evidence=choose(state,actions,steps-index,policy,config['remote'])
                    policy_elapsed=time.monotonic()-choice_started
                    if decision['action_id'] is None:
                        state['policy_stop']={'decision':decision,'policy_evidence':evidence,'policy_elapsed_seconds':policy_elapsed,
                                              'control_sources':control_sources,'git_revision':revision(),'created_at_unix':time.time(),'strategy_context_version':4,'controller_action_version':2}
                        state['status']='policy_stopped';atomic_json(path,state);break
                    action=next(row for row in actions if row['id']==decision['action_id'])
                    intent={'action':action,'decision':decision,'policy_evidence':evidence,'status':'reserved',
                            'strategy_context_version':4,'controller_action_version':2,
                            'control_sources':control_sources,'git_revision':revision(),'policy_elapsed_seconds':policy_elapsed,
                            'created_at_unix':time.time(),'tool_attempts':[]}
                    state['intent']=intent;atomic_json(path,state)
                # Only fixed, idempotent tools may resume an interrupted intent.
                # submit reconciles the existing durable Training run ID.
                if intent.get('control_sources')!=control_sources:
                    raise ValueError('Pending action uses different control source; restore its frozen source before resuming')
                control_versions(intent)
                attempt={'started_at_unix':time.time(),'status':'started'}
                intent.setdefault('tool_attempts',[]).append(attempt);atomic_json(path,state)
                tool_started=time.monotonic()
                try:result=execute(intent['action'],state,session,config,folder,runs)
                except Exception as error:
                    from .llm import LLMNotDispatched
                    if isinstance(error,LLMNotDispatched) and intent['action']['kind']=='propose_experiment':
                        attempt.update(status='not_dispatched',elapsed_seconds=time.monotonic()-tool_started)
                        intent['status']='not_dispatched'
                        state.update(status='action_not_dispatched',paused=True,last_error=str(error))
                        atomic_json(path,state)
                        raise
                    attempt.update(status='uncertain',elapsed_seconds=time.monotonic()-tool_started)
                    state['status']='action_uncertain';state['last_error']=type(error).__name__+': '+str(error)
                    atomic_json(path,state);raise
                attempt.update(status='completed',elapsed_seconds=time.monotonic()-tool_started)
                project(state,intent['action'],result)
                state['history'].append(dict(intent,status='completed',result=result))
                state['intent']=None;state.pop('last_error',None);atomic_json(path,state)
                if state['status'] in ('waiting','blocked'):break
        finally:runs.close()
    return dict(state,state_path=str(path.resolve()),controller_tool_budget=control_budget(state))
