"""Read-only verification of preregistered GPU caps and per-arm API quotas."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .llm import request_payload
from .llm_usage import admission_trigger_verified, validate_call_limit
from .runner import digest


def finite(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def api_quota(bound, campaign_root, limit, registered_at):
    validate_call_limit(limit)
    settings=dict(bound['execution_config']['llm'])
    if settings.get('usage_call_limit')!=limit:raise ValueError('Arm API cap differs from preregistration')
    path=Path(settings['usage_ledger'])
    if not path.is_absolute() or path.is_symlink():raise ValueError('Arm API ledger must be an absolute non-symlink file')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        db.execute('BEGIN')
        cap=db.execute('SELECT calls FROM api_call_cap WHERE singleton=1').fetchone()
        if cap!=(limit,) or not admission_trigger_verified(db):raise ValueError('Arm API cap or admission trigger differs')
        rows=db.execute('SELECT id,request_sha256,model,created_ns,status,prompt_tokens,completion_tokens,total_tokens FROM api_usage').fetchall()
    finally:db.close()
    if len(rows)>limit:raise ValueError('Arm API admissions exceed preregistered cap')
    records={row[0]:row for row in rows};linked=set();tokens=0;unsent=0
    requests=Path(campaign_root)/bound['session_id']/bound['campaign_id']/'experiments/requests.sqlite3'
    if requests.exists():
        db=sqlite3.connect(requests.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        try:
            db.execute('BEGIN');proposals=db.execute('SELECT context,state,response FROM requests').fetchall()
        finally:db.close()
    else:proposals=[]
    for context,state,response in proposals:
        if state=='not_dispatched' and response is None:unsent+=1;continue
        if state!='responded' or response is None:raise ValueError('Unsettled arm API proposal')
        context=json.loads(context);response=json.loads(response);key=response.get('usage_record_id')
        if not isinstance(key,str) or key not in records or key in linked:raise ValueError('Missing, duplicated or foreign API usage receipt')
        linked.add(key);row=records[key];snapshot=context.get('request_snapshot')
        if not isinstance(snapshot,dict) or digest(snapshot)!=context.get('request_snapshot_sha256'):raise ValueError('API request snapshot differs')
        if context.get('llm')!={key:settings[key] for key in ('model','base_url','usage_ledger','usage_call_limit','thinking') if key in settings}:
            raise ValueError('API proposal model or ledger differs from registered arm')
        effective=dict(settings)
        if effective['model']=='deepseek-flash':effective.setdefault('thinking','disabled')
        payload=request_payload(effective,snapshot['messages'],snapshot['max_tokens'])
        expected=hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        usage=response.get('usage') or {};numbers=[usage.get(key) for key in ('prompt_tokens','completion_tokens','total_tokens')]
        if any(type(value) is not int or not 0<=value<=2**53 for value in numbers) or numbers[0]+numbers[1]!=numbers[2]:raise ValueError('API token evidence incomplete')
        if (row[1]!=expected or row[2]!=settings['model'] or type(row[3]) is not int or row[3]/1e9<registered_at
                or row[4]!='responded' or tuple(numbers)!=row[5:]):raise ValueError('API receipt payload, model, time or token linkage differs')
        tokens+=numbers[2]
    if linked!=set(records):raise ValueError('Unattributed or uncertain API ledger admissions')
    return {'ledger':str(path.resolve()),'call_limit':limit,'admitted_calls':len(rows),'known_tokens':tokens,
            'not_dispatched_proposals':unsent,'linked_usage_ids':sorted(linked),'receipt_linkage_verified':True,
            'admission_rule_verified':True,'scope':'Registered arm campaign experiment proposals only'}


def compare_budgets(pair, audits, campaign_root, registered_at, call_limit=None):
    missing=[];gpu={};api={}
    for arm in ('baseline','candidate'):
        try:
            bound=pair[arm];result=audits[arm];cap=bound['binding']['contract']['budget']['gpu_hours']
            actual=result.get('settled_gpu_hours');held=result.get('held_gpu_hours')
            if (not finite(cap) or cap<=0 or not finite(result.get('authorized_gpu_hours')) or result.get('authorized_gpu_hours')!=cap
                    or result.get('gpu_accounting_settled') is not True or not finite(actual)
                    or held!=0 or type(held) is bool or actual>cap+1e-12):raise ValueError('GPU cap or settled accounting differs')
            gpu[arm]={'cap_gpu_hours':cap,'settled_gpu_hours':actual}
            if call_limit is not None:
                receipt=api_quota(bound,campaign_root,call_limit,registered_at)
                if (type(result.get('llm_admitted_or_uncertain_count')) is not int or type(result.get('known_llm_tokens')) is not int
                        or receipt['admitted_calls']!=result['llm_admitted_or_uncertain_count'] or receipt['known_tokens']!=result['known_llm_tokens']):
                    raise ValueError('Campaign API accounting differs from linked quota ledger')
                api[arm]=receipt
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as error:missing.append(arm+': '+str(error))
    gpu_equal=len(gpu)==2 and gpu['baseline']['cap_gpu_hours']==gpu['candidate']['cap_gpu_hours']
    api_equal=len(api)==2
    if api_equal:
        left=Path(api['baseline']['ledger']);right=Path(api['candidate']['ledger'])
        if left==right or left.samefile(right):api_equal=False;missing.append('Arm API ledgers share one file')
    if not gpu_equal:missing.append('Equal settled authorized GPU caps not verified')
    if call_limit is not None and not api_equal:missing.append('Independent equal API call caps not verified')
    return {'gpu':gpu,'api':api,'equal_gpu_caps_verified':gpu_equal,'independent_equal_api_call_caps_verified':api_equal,
            'registered_dimensions_verified':not missing,'missing_evidence':missing,
            'full_resource_budgets_verified':False,'rsi_efficiency_verified':False,
            'scope':'Authorized GPU hours and optional campaign API call limits; not CPU, total wall time, tokens, money or whole-project history'}
