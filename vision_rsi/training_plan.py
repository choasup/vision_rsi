"""Bind a Training contract to an explicit executable first-task recipe."""
import json
import math
from pathlib import Path

from .contracts import issues
from .coco_train import validate_recipe
from .filesystem import native_path
from .runner import atomic_json, digest, revision


DEFAULT_RECIPE={'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','epochs':1,'batch_size_per_gpu':2,
                'seed':42,'checkpoint_steps':100,'world_size':8,'min_size':800,'max_size':1333,
                'learning_rate':.001,'weight_decay':.0001,'fixture':False}


def budget_blockers(contract):
    """Never silently execute against a cap this Training path cannot enforce."""
    if contract.get('gpu_budget_scope','session') not in ('session','experiment'):
        return ['Unsupported GPU budget scope']
    budget=contract.get('budget')
    if budget is None:return []
    if not isinstance(budget,dict):return ['Training budget must be an object']
    return ['Training cannot enforce budget.'+str(key)+' across stages; execution blocked'
            for key in sorted(budget,key=str) if key!='gpu_hours']


def require_supported_budget(contract):
    blockers=budget_blockers(contract)
    if blockers:raise ValueError('; '.join(blockers))


def prepare(session,config,root):
    if not session['versions']: raise ValueError('Define the task interface before preparing training')
    latest=session['versions'][-1];contract=latest['contract']
    if not isinstance(contract,dict):raise ValueError('Training contract must be an object; repair task requirements first')
    remote=config.get('remote') or {}
    if not isinstance(remote,dict):raise ValueError('remote config must be an object')
    blockers=list(issues(contract))
    if session.get('pending_request'):blockers.append('需求请求尚未处理；先完成澄清或恢复，不能按旧要求执行。')
    blockers.extend(budget_blockers(contract))
    blockers.extend('待确认需求变更: '+change['path'] for change in latest.get('review_required',[]))
    from .task_adapters import training_adapter
    adapter=training_adapter(contract)
    blockers.extend(adapter['blockers'])
    acceptance=contract.get('acceptance')
    acceptance=acceptance if isinstance(acceptance,dict) else {}
    training=config.get('training') or {}
    if not isinstance(training,dict): raise ValueError('training config must be an object')
    recipe=dict(DEFAULT_RECIPE,**training)
    recipe['coco_root']=remote.get('coco_root') or training.get('coco_root','')
    recipe['acceptance_threshold']=acceptance.get('threshold')
    recipe['fixture']=False  # User tasks can never silently become fixture runs.
    recipe.pop('timeout_seconds',None)
    try: validate_recipe(recipe,path_flavor='posix')
    except (ValueError,KeyError) as error: blockers.append('训练执行配置待补充: '+str(error))
    world=recipe.get('world_size')
    valid_world=isinstance(world,int) and not isinstance(world,bool) and 1<=world<=8
    declared_budget=contract.get('budget')
    budget=declared_budget.get('gpu_hours') if isinstance(declared_budget,dict) else None
    if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or budget<=0:
        blockers.append('需要任务 budget.gpu_hours 的真实训练预算，mock预算不能用于执行。')
        timeout=None
    elif not valid_world:
        timeout=None
        blockers.append('有效的 world_size 是调度前提。')
    else:
        allocation=1 if contract.get('gpu_budget_scope')=='experiment' else 3
        timeout=training.get('timeout_seconds',max(0,int(budget*3600/world/allocation)-5))
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0 or (timeout+5)*recipe['world_size']/3600>budget:
            blockers.append('训练超时与GPU卡数超过任务预算。')
    # Timeout belongs to the scheduler, not the torch model recipe.
    recipe.pop('timeout_seconds',None)
    sources={p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}
    plan={'task_id':session['task_id'],'session_id':session['session_id'],'contract_version':latest['version'],
          'contract':contract,'recipe':recipe,'task_adapter':adapter,'source_hashes':sources,'git_revision':revision(),
          'scheduler':{'gpu_devices':list(range(recipe['world_size'])) if isinstance(recipe.get('world_size'),int) and 1<=recipe['world_size']<=8 else [],
                       'timeout_seconds':timeout,'gpu_hours_budget':budget},
          'status':'blocked' if blockers else 'ready_to_submit','blockers':blockers,
          'limitations':['Frozen baseline only; method research and Agent RSI loop still pending.','Baseline performance is measured, never assumed to meet the target.']}
    identity=digest(plan)
    folder=native_path(Path(root)/session['task_id']/identity);folder.mkdir(parents=True,exist_ok=True)
    destination=native_path(folder/'plan.json')
    if destination.exists():
        if json.loads(destination.read_text(encoding='utf-8'))!=plan: raise ValueError('Training plan hash conflict')
    else: atomic_json(destination,plan)
    return dict(plan,plan_id=identity,plan_path=str(destination.resolve()),training_performed=False)
