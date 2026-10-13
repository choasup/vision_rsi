"""Task-bound executable-harness requirements, independent of any detector."""
import json
from pathlib import Path

from .runner import atomic_json,digest
from .task_adapters import training_adapter


STAGES=('load_data','train','predict','evaluate')


def plan(session,root):
    if session.get('pending_request') or not session.get('versions'):
        raise ValueError('Resolve task requirements before harness planning')
    latest=session['versions'][-1]
    if latest.get('review_required'):
        raise ValueError('Review requirement changes before harness planning')
    contract=latest['contract']
    if not isinstance(contract.get('inputs'),dict) or not contract['inputs']:
        raise ValueError('Task input interface missing')
    if not isinstance(contract.get('output_schema'),dict):
        raise ValueError('Task output interface missing')
    acceptance=contract.get('acceptance') or {}
    adapter=training_adapter(contract)
    classification=(acceptance.get('metric')=='accuracy'
                    and {'label','confidence'}<=set(contract['output_schema'].get('properties',{})))
    family='coco_detection' if adapter['implementation_supported'] else 'image_classification' if classification else 'custom_visual'
    resources=configured_resources(contract)
    requirements={
        'format_version':1,'task_id':session['task_id'],'session_id':session['session_id'],
        'contract_version':latest['version'],'contract':contract,
        'contract_sha256':digest(contract),'task_family':family,
        'resource_requirements':resources,
        'execution_backend':adapter['adapter_id'],
        'required_stages':list(STAGES),
        'stage_contracts':{
            'load_data':'Frozen data manifest, class mapping and disjoint training/development/acceptance splits',
            'train':'Checkpoint plus source, dependency, recipe and resource execution receipts',
            'predict':'Contract samples to contract outputs; no ground truth in prediction process',
            'evaluate':'Host-owned fixed metric protocol on complete sample IDs; never candidate self-scoring'},
        'code_generation_constraints':[
            'Candidate source tracked in Git; no direct mutation of controller or evaluator',
            'Dependencies and pretrained artifacts pinned before execution',
            'Smoke check before GPU reservation; execution only through accounted scheduler',
            'Development feedback may guide iteration; independent acceptance is not search feedback'],
        'missing_backend':not adapter['implementation_supported'],
        'training_performed':False,'quality_verified':False,
        'next_step':'prepare_existing_backend' if adapter['implementation_supported'] else 'generate_and_validate_task_backend',
        'status':'existing_backend_available' if adapter['implementation_supported'] else 'harness_implementation_required'}
    identity=digest(requirements)
    folder=Path(root).resolve()/session['session_id']/identity
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'harness-plan.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=requirements:
            raise ValueError('Frozen harness requirements changed')
    else:atomic_json(path,requirements)
    return dict(requirements,plan_id=identity,plan_path=str(path))


def configured_resources(contract):
    """Describe missing execution facts without inventing dataset permission.

    Dataset selection/binding is a later executable step, not satisfied by an
    example_input URI or a budget already supplied for training.
    """
    acceptance=contract.get('acceptance') or {}
    source=contract.get('data_source')
    source=source if isinstance(source,dict) else {}
    classes=(contract.get('output_schema') or {}).get('properties',{}).get('label',{}).get('enum')
    budget=contract.get('budget')
    result={'status':'resource_binding_required','class_labels_from_contract':classes,
            'gpu_budget_from_contract':budget.get('gpu_hours') if isinstance(budget,dict) else None,
            'dataset_bound':False,'example_uri_is_dataset':False,
            'declared_data_source':contract.get('data_source'),
            'clarification_questions':[
                {'id':'dataset_source','question':'训练数据使用你已有的数据，还是允许 Agent 选择公开数据集？已有数据请说明位置；公开数据请说明允许自动下载。',
                 'reason':'训练和评测需要真实数据来源；示例图片地址不代表数据集已存在或获准下载。'}] if source.get('kind') not in ('local','public') or not source.get('location') else [],
            'host_owned_followups':['核查数据内容、标签映射和实际可读路径',
                                    '固定训练/开发/独立验收切分及哈希',
                                    '固定依赖和预训练权重来源',
                                    '复核原任务指标、刻度与剩余预算'],
            'acceptance_metric':acceptance.get('metric'),
            'scope':'Questions only; no resource inspection, download or user authorization inferred.'}

    if budget is not None and not isinstance(budget,dict):
        result['budget_issue']='预算格式无效：需要对象（例如 gpu_hours 字段）；原始值已保留，未推定资源授权。'
    return result
