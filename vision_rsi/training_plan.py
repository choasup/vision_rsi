"""Bind a Training contract to an explicit executable first-task recipe."""
import json
import math
from pathlib import Path

from .contracts import issues, validate_schema
from .coco_train import validate_recipe
from .runner import atomic_json, digest, revision


DEFAULT_RECIPE={'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','epochs':1,'batch_size_per_gpu':2,
                'seed':42,'checkpoint_steps':100,'world_size':8,'min_size':800,'max_size':1333,
                'learning_rate':.001,'weight_decay':.0001,'fixture':False}


def prepare(session,config,root):
    if not session['versions']: raise ValueError('Define the task interface before preparing training')
    latest=session['versions'][-1];contract=latest['contract']
    blockers=list(issues(contract))
    blockers.extend('待确认需求变更: '+change['path'] for change in latest.get('review_required',[]))
    inputs=contract.get('inputs') or {}
    if len(inputs)!=1 or any(not isinstance(x,dict) or x.get('type')!='image' or x.get('required') is not True for x in inputs.values()):
        blockers.append('当前 COCO baseline 适配器仅实现一个必需 image 输入；其他任务保留接口，不假装已实现。')
    acceptance=contract.get('acceptance') or {}
    if acceptance.get('metric') not in ('AP','box_AP','bbox_AP') or acceptance.get('direction')!='maximize' or 'coco' not in str(acceptance.get('evaluation_protocol','')).lower():
        blockers.append('此适配器要求 COCO bbox AP 标准协议；未自动转换其他任务指标。')
    try: validate_schema(contract.get('output_schema'),{'detections':[{'bbox':[0.,0.,1.,1.],'category_id':1,'score':.5}]})
    except (ValueError,TypeError,KeyError):blockers.append('任务输出接口与 COCO detections 适配器不兼容。')
    training=config.get('training') or {}
    if not isinstance(training,dict): raise ValueError('training config must be an object')
    recipe=dict(DEFAULT_RECIPE,**training)
    recipe['coco_root']=config.get('remote',{}).get('coco_root') or training.get('coco_root','')
    recipe['acceptance_threshold']=acceptance.get('threshold')
    recipe['fixture']=False  # User tasks can never silently become fixture runs.
    recipe.pop('timeout_seconds',None)
    try: validate_recipe(recipe,path_flavor='posix')
    except (ValueError,KeyError) as error: blockers.append('训练执行配置待补充: '+str(error))
    world=recipe.get('world_size')
    valid_world=isinstance(world,int) and not isinstance(world,bool) and 1<=world<=8
    budget=(contract.get('budget') or {}).get('gpu_hours')
    if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or budget<=0:
        blockers.append('需要任务 budget.gpu_hours 的真实训练预算，mock预算不能用于执行。')
        timeout=None
    elif not valid_world:
        timeout=None
        blockers.append('有效的 world_size 是调度前提。')
    else:
        timeout=training.get('timeout_seconds',max(0,int(budget*3600/world/3)-5))
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0 or (timeout+5)*recipe['world_size']/3600>budget:
            blockers.append('训练超时与GPU卡数超过任务预算。')
    # Timeout belongs to the scheduler, not the torch model recipe.
    recipe.pop('timeout_seconds',None)
    sources={p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}
    plan={'task_id':session['task_id'],'session_id':session['session_id'],'contract_version':latest['version'],
          'contract':contract,'recipe':recipe,'source_hashes':sources,'git_revision':revision(),
          'scheduler':{'gpu_devices':list(range(recipe['world_size'])) if isinstance(recipe.get('world_size'),int) and 1<=recipe['world_size']<=8 else [],
                       'timeout_seconds':timeout,'gpu_hours_budget':budget},
          'status':'blocked' if blockers else 'ready_to_submit','blockers':blockers,
          'limitations':['Frozen baseline only; method research and Agent RSI loop still pending.','Baseline performance is measured, never assumed to meet the target.']}
    identity=digest(plan)
    folder=Path(root)/session['task_id']/identity;folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'plan.json'
    if destination.exists():
        if json.loads(destination.read_text(encoding='utf-8'))!=plan: raise ValueError('Training plan hash conflict')
    else: atomic_json(destination,plan)
    return dict(plan,plan_id=identity,plan_path=str(destination.resolve()),training_performed=False)
