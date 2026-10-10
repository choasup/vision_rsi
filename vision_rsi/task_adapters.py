"""Deterministic task compatibility, separate from interface and quality checks."""
from .contracts import validate_schema
from .detector import COCO_IDS


def training_adapter(contract):
    blockers=[]
    inputs=contract.get('inputs')
    inputs=inputs if isinstance(inputs,dict) else {}
    if len(inputs)!=1 or any(not isinstance(x,dict) or x.get('type')!='image' or x.get('required') is not True for x in inputs.values()):
        blockers.append('当前 COCO baseline 适配器仅实现一个必需 image 输入；其他任务保留接口，不假装已实现。')
    acceptance=contract.get('acceptance')
    acceptance=acceptance if isinstance(acceptance,dict) else {}
    if acceptance.get('metric') not in ('AP','box_AP','bbox_AP') or acceptance.get('direction')!='maximize' or 'coco' not in str(acceptance.get('evaluation_protocol','')).lower():
        blockers.append('此适配器要求 COCO bbox AP 标准协议；未自动转换其他任务指标。')
    try:
        validate_schema(contract.get('output_schema'),{'detections':[]})
        for category in COCO_IDS:
            validate_schema(contract.get('output_schema'),{'detections':[{'bbox':[0.,0.,1.,1.],'category_id':category,'score':.5}]})
    except (ValueError,TypeError,KeyError):blockers.append('任务输出接口与 COCO detections 适配器不兼容。')
    return {'adapter_id':'coco_detection_v1' if not blockers else None,'implementation_supported':not blockers,
            'blockers':blockers,'training_performed':False,'model_quality_verified':False,
            'scope':'Contract compatibility only; runtime configuration, budget and measured quality require separate checks.'}
