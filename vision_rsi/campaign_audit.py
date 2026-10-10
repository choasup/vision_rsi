"""Read-only cost and measurement audit; never a self-reported RSI verdict."""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import quote

from .acceptance import review
from .runner import digest
from .training_runs import TrainingRuns
from .policy_audit import verify_trace


def finite(value):return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>=0


def audit(session_id,campaign_id,root='runs/campaigns',run_store='runs/training-runs'):
    if not isinstance(session_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',session_id):raise ValueError('Invalid session ID')
    if not isinstance(campaign_id,str) or not re.fullmatch('[0-9a-f]{64}',campaign_id):raise ValueError('Invalid campaign ID')
    path=Path(root)/session_id/campaign_id/'state.json';raw=path.read_bytes();state=json.loads(raw)
    binding=state['binding']
    if digest(binding)!=campaign_id or state['campaign_id']!=campaign_id or binding['session_id']!=session_id:raise ValueError('Campaign identity changed')
    if Path(binding['run_store']).resolve()!=Path(run_store).resolve():raise ValueError('Audit must use the frozen Training ledger')
    db_path=Path(run_store)/'training-runs.sqlite3'
    if not db_path.is_file():raise ValueError('Training ledger missing; audit will not create one')
    store=TrainingRuns(run_store,read_only=True)
    try:
        store.db.execute('BEGIN')
        records=store.list(session_id)
    finally:store.close()
    missing=[];measurements=[];actual=0.;reserved=0.;settled=True
    referenced={row['result']['run_id'] for row in state['history'] if row['action']['kind']=='submit' and isinstance(row.get('result'),dict) and row['result'].get('run_id')}
    if state.get('run_id'):referenced.add(state['run_id'])
    unattributed=[row['run_id'] for row in records if row['run_id'] not in referenced]
    if unattributed:missing.append('Session contains Training runs outside this campaign trace')
    for record in records:
        if not finite(record['reserved_gpu_hours']):raise ValueError('Invalid Training reservation')
        if record['actual_gpu_hours'] is None:
            reserved+=record['reserved_gpu_hours'];settled=False
        elif finite(record['actual_gpu_hours']):actual+=record['actual_gpu_hours']
        else:raise ValueError('Invalid settled GPU accounting')
        if record['run_id'] not in referenced or record['status']!='completed':continue
        try:
            plan=json.loads(Path(record['details']['plan_path']).read_text(encoding='utf-8'))
            if digest(plan)!=record['plan_id']:raise ValueError('Frozen Training plan changed')
            if plan.get('session_id')!=session_id or plan.get('contract')!=binding['contract']:
                raise ValueError('Measurement belongs to different session requirements')
            receipt_path=Path(record['details']['receipt_path']);receipt_raw=receipt_path.read_bytes();receipt=json.loads(receipt_raw)
            if receipt['run_id']!=record['run_id']:raise ValueError('Receipt run identity differs')
            verdict=review(plan,receipt)
            eligible=not any(reason!='Measured box AP is below task requirement' for reason in verdict['reasons'])
            measurements.append({'run_id':record['run_id'],'box_AP':verdict['box_AP'],'threshold':verdict['threshold'],
                                 'receipt_sha256':hashlib.sha256(receipt_raw).hexdigest(),'plan_id':record['plan_id'],
                                 'training_identity':verdict['training_identity'],
                                 'eligible_real_coco_measurement':eligible,'target_met':verdict['passed']})
            if not eligible:missing.append('Fixture/subset measurement cannot support a real RSI comparison: '+record['run_id'])
        except (ValueError,TypeError,KeyError,OSError) as error:
            missing.append('Unverified completed run '+record['run_id']+': '+str(error))
    if not settled:missing.append('Active/uncertain Training reservations remain')
    budget=(binding.get('contract',{}).get('budget') or {}).get('gpu_hours')
    if not finite(budget) or budget<=0:missing.append('No valid authorized GPU budget')
    elif actual+reserved>budget+1e-12:missing.append('Session GPU accounting exceeds authorized budget')
    elapsed=0.;timing_complete=True
    for row in state['history']+([state['intent']] if state.get('intent') else []):
        selection=row.get('policy_elapsed_seconds');attempts=row.get('tool_attempts')
        if not finite(selection) or not isinstance(attempts,list) or not attempts:
            timing_complete=False;continue
        elapsed+=selection
        for attempt in attempts:
            value=attempt.get('elapsed_seconds')
            if not finite(value):timing_complete=False
            else:elapsed+=value
    if state.get('policy_stop'):
        value=state['policy_stop'].get('policy_elapsed_seconds')
        if finite(value):elapsed+=value
        else:timing_complete=False
    if not timing_complete:missing.append('Action wall-time evidence incomplete; interrupted/legacy time is not zero')
    if state.get('intent'):missing.append('Unresolved controller action remains')
    token_total=0;token_complete=True;api_requests=0;not_dispatched=0;admitted_requests=0
    api_path=path.parent/'experiments/requests.sqlite3'
    expected_requests=sum(1 for row in state['history'] if row['action']['kind']=='propose_experiment' and row.get('result',{}).get('status')!='budget_exhausted')
    if api_path.is_file():
        db=sqlite3.connect('file:'+quote(str(api_path.resolve()).replace('\\','/'),safe='/:')+'?mode=ro',uri=True)
        try:requests=db.execute('SELECT id,state,response FROM requests').fetchall()
        finally:db.close()
        api_requests=len(requests)
        for request_id,status,response in requests:
            if status=='not_dispatched' and response is None:
                not_dispatched+=1
                continue
            admitted_requests+=1
            if status!='responded' or response is None:token_complete=False;continue
            value=json.loads(response);usage=value.get('usage') or {}
            numbers=[usage.get(key) for key in ('prompt_tokens','completion_tokens','total_tokens')]
            if any(isinstance(number,bool) or not isinstance(number,int) or number<0 for number in numbers) or numbers[0]+numbers[1]!=numbers[2]:
                token_complete=False
            else:token_total+=numbers[2]
    if admitted_requests!=expected_requests:token_complete=False
    if not token_complete:missing.append('LLM usage missing or uncertain; unreported tokens are not zero')
    try:policy_trace=verify_trace(state)
    except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError) as error:
        policy_trace={'verified':False,'error':str(error)}
        missing.append('Policy trace unverified: '+str(error))
    if not measurements:missing.append('No verified completed measurement')
    scores=[row['box_AP'] for row in measurements if row['eligible_real_coco_measurement']]
    return {'campaign_id':campaign_id,'session_id':session_id,'campaign_state_sha256':hashlib.sha256(raw).hexdigest(),
            'scope':'Whole-session GPU accounting; measurements from runs referenced by this campaign only',
            'authorized_gpu_hours':budget,'settled_gpu_hours':actual,'held_gpu_hours':reserved,'gpu_accounting_settled':settled,
            'observed_action_wall_seconds':elapsed,'action_timing_complete':timing_complete,
            'known_llm_tokens':token_total,'llm_usage_complete':token_complete,'llm_request_count':api_requests,
            'llm_not_dispatched_count':not_dispatched,'llm_admitted_or_uncertain_count':admitted_requests,
            'llm_cost_scope':'Campaign experiment proposals only; task clarification and candidate-generation setup excluded',
            'measurements':measurements,'best_verified_real_box_AP':max(scores) if scores else None,
            'policy_trace':policy_trace,
            'unattributed_run_ids':unattributed,'evidence_complete_for_review':not missing,'missing_evidence':missing,
            'rsi_efficiency_verified':False,'agent_adopted':False,
            'limitation':'Independent single-campaign audit only; no paired held-out study or RSI improvement established.'}
