"""Dashboard adapter for the existing accounted Training execution path."""
from pathlib import Path
import json

from .campaign import lease
from .training_plan import prepare
from .training_runs import TrainingRuns, submit, observe, collect, remote_identity


def advance_training(session, config, storage):
    """Prepare and submit once, then reconcile the same durable run on subsequent calls."""
    root = Path(storage)
    folder=root/'dashboard-training'/session['session_id']
    folder.mkdir(parents=True,exist_ok=True)
    with lease(folder/'execution.lock'):
        runs = TrainingRuns(root/'training-runs')
        try:
            remote = config.get('remote') or {}
            records = runs.list(session['session_id'])
            if records:
                record = records[-1]
                if record['remote'] != remote_identity(remote):
                    return {'status':'blocked','message':'训练目标机器配置已变化；请恢复原配置后查询已有作业，未重复提交。','run_id':record['run_id']}
                if record['status'] in ('deployment_failed','reserved'):
                    return {'status':'blocked','run':record,'message':'已有运行在准备阶段中断。请核对原记录后恢复，未重复提交。'}
                if record['status'] in ('failed','cancelled','timed_out'):
                    return {'status':record['status'],'run':record,'message':'原训练已结束：'+record['status']+'。保留结果，未自动重新消耗预算。'}
                if record['details'].get('acceptance_review'):
                    return present(record)
                record = observe(record['run_id'],remote,runs)
                if record['status']=='completed':
                    record=collect(record['run_id'],remote,runs)
                return present(record)
            plan = prepare(session,config,root/'training-plans')
            blockers = list(plan['blockers'])
            for key,label in (('ssh_host','训练机器 SSH 地址'),('workspace','训练机器工作目录')):
                if not remote.get(key):blockers.append('未配置'+label+'（remote.'+key+'）。')
            if blockers:
                return {'status':'blocked','message':'实验尚未启动：\n'+'\n'.join('- '+b for b in blockers),
                        'blockers':blockers,'plan_path':plan['plan_path'],'training_performed':False}
            try:
                return present(submit(plan,remote,runs))
            except Exception as error:
                records=runs.list(session['session_id'])
                return {'status':'blocked','message':'训练提交未能确认：'+str(error)+'。已保留原运行记录，不会自动重新提交。',
                        'run':records[-1] if records else None}
        finally:
            runs.close()


def present(record):
    state=record['status']
    messages={'submitted':'训练作业已提交，正在等待执行状态。','running':'训练作业正在运行。',
              'waiting':'训练作业正在等待资源。','completed':'训练进程已结束，评测证据见运行记录。',
              'submission_uncertain':'提交响应不确定，正在查询原作业；不会重复提交。'}
    return {'status':state,'run':record,'run_id':record['run_id'],
            'message':messages.get(state,'训练状态：'+state)}
