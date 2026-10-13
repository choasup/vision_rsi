"""Read-only local prerequisites; no submission, API probe or quality verdict."""
import math
from pathlib import Path
from .contracts import Sessions,issues
from .runner import doctor
from .task_adapters import training_adapter
from .training_plan import budget_blockers
from .training_runs import TrainingRuns
from .runner import digest


def inspect(session_id,config,sessions,runs,config_path='config.local.json'):
    session=Sessions(sessions,read_only=True).show(session_id)
    latest=session['versions'][-1] if session['versions'] else {}
    contract=latest.get('contract') or {}
    blockers=issues(contract) if contract else ['任务尚未形成接口']
    if session.get('pending_request'):blockers.append('需求请求未完成处理')
    if latest.get('review_required'):blockers.append('需求变更尚未确认')
    adapter=training_adapter(contract)
    blockers.extend(adapter['blockers']);blockers.extend(budget_blockers(contract))
    budget=contract.get('budget')
    budget=budget.get('gpu_hours') if isinstance(budget,dict) else None
    authorized=not isinstance(budget,bool) and isinstance(budget,(int,float)) and math.isfinite(budget) and budget>0
    if not authorized:blockers.append('尚无有效的真实GPU小时预算')
    configuration=doctor(config)
    if not configuration['configuration_ready']:blockers.append('本地配置检查未通过；使用doctor查看配置状态')
    records=[];remaining=budget if authorized else None
    if (Path(runs)/'training-runs.sqlite3').exists():
        ledger=TrainingRuns(runs,read_only=True)
        try:
            records=ledger.list(session_id)
            if authorized:
                remaining=budget if contract.get('gpu_budget_scope')=='experiment' else ledger.remaining(session_id,budget)
        finally:ledger.close()
    for record in records:
        cost=record['actual_gpu_hours'] if record['actual_gpu_hours'] is not None else record['reserved_gpu_hours']
        if isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:raise ValueError('Invalid recorded GPU accounting')
    if authorized and (not math.isfinite(remaining) or not 0<=remaining<=budget):raise ValueError('Invalid remaining GPU snapshot')
    unsettled=[r['run_id'] for r in records if r['actual_gpu_hours'] is None]
    if unsettled:blockers.append('存在未结算或不确定的训练预留；先查询原运行')
    if authorized and remaining<=0:blockers.append('GPU小时预算已耗尽')
    actions=[]
    common=['--session-id',session_id,'--sessions',str(sessions)]
    def action(kind,arguments,reason,user_value=False):
        actions.append({'action':kind,'argv':['training',kind]+common+arguments,
                        'reason':reason,'requires_user_value':user_value,'executed':False})
    if unsettled:
        action('runs',['--run-store',str(runs)],'查询原运行，先解决未结算或不确定的预留')
    if (not authorized and adapter['implementation_supported'] and not session.get('pending_request')
            and not latest.get('review_required')):
        action('budget',['--gpu-hours','<GPU_HOURS>'],'由用户指定初始GPU小时上限；占位符不是授权',True)
    if not blockers:
        action('prepare',['--config',str(config_path),'--run-store',str(runs)],'仅编译并检查训练计划；不等于提交作业')
    else:
        action('show',[],'查看当前任务定义和待处理需求')
    return {'task_id':session['task_id'],'session_id':session_id,'contract_version':latest.get('version'),
            'status':'blocked' if blockers else 'ready_for_prepare','blockers':list(dict.fromkeys(blockers)),
            'training_adapter':adapter,'configuration':configuration,'authorized_gpu_hours':budget if authorized else None,
            'remaining_gpu_hours_snapshot':remaining,'recorded_runs':len(records),'unsettled_run_ids':unsettled,
            'recent_run_ids':[record['run_id'] for record in records[-10:]],
            'recent_run_snapshots':[{'run_id':record['run_id'],'record_sha256':digest(record),'recorded_status':record['status']} for record in records[-10:]],
            'run_list_truncated':len(records)>10,
            'suggested_actions':actions,
            'read_only':True,'remote_called':False,'llm_called':False,'training_performed':False,
            'task_quality_status':'not_checked','release_verified':False,
            'scope':'Local prerequisites only; prepare/runtime preflight and actual training/serving evidence remain required.'}
