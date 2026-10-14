"""Deterministic detection of changes to an established task definition."""
import copy
import json


def changes(previous,proposed):
    if not isinstance(previous,dict) or not isinstance(proposed,dict):return []
    result=[]
    def schema_semantics(schema):
        if not isinstance(schema,dict):return schema
        result={k:v for k,v in schema.items() if k!='description'}
        if isinstance(result.get('properties'),dict):
            result['properties']={k:schema_semantics(v) for k,v in result['properties'].items()}
        if 'items' in result:result['items']=schema_semantics(result['items'])
        return result
    def equal(a,b):return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)
    def compare(path,before,after):
        if path=='output_schema' and equal(schema_semantics(before),schema_semantics(after)):return
        if path=='inputs' and isinstance(before,dict) and isinstance(after,dict):
            if equal({k:schema_semantics(v) for k,v in before.items()},{k:schema_semantics(v) for k,v in after.items()}):return
        if json.dumps(before,sort_keys=True,allow_nan=False)!=json.dumps(after,sort_keys=True,allow_nan=False):
            result.append({'path':path,'before':copy.deepcopy(before),'after':copy.deepcopy(after)})
    if previous.get('goal'):
        compare('goal',previous['goal'],proposed.get('goal'))
    for key in ('inputs','output_schema','data_source'):
        if previous.get(key):compare(key,previous[key],proposed.get(key))
    old=previous.get('acceptance') or {};new=proposed.get('acceptance') or {}
    if isinstance(old,dict):
        for key,value in old.items():
            if value is not None and value!='':compare('acceptance.'+key,value,new.get(key) if isinstance(new,dict) else None)
    # Once a task exists, a model cannot create or alter resource authorization.
    if previous.get('budget') or proposed.get('budget'):compare('budget',previous.get('budget'),proposed.get('budget'))
    if previous.get('gpu_budget_scope') or proposed.get('gpu_budget_scope'):
        compare('gpu_budget_scope',previous.get('gpu_budget_scope'),proposed.get('gpu_budget_scope'))
    return result


def review_lines(review):
    """Describe decisions without exposing schema dictionaries to the user."""
    labels={'goal':'任务目标','inputs':'输入内容','output_schema':'输出内容',
            'data_source':'数据来源','acceptance.metric':'验收指标',
            'acceptance.threshold':'效果目标','acceptance.direction':'指标方向',
            'acceptance.evaluation_protocol':'评测方法','budget':'资源预算',
            'gpu_budget_scope':'预算范围'}
    def value(path,item):
        if item is None:return '未设置'
        if path=='budget' and isinstance(item,dict):
            return '、'.join(str(v)+' GPU 小时' if k=='gpu_hours' else str(k)+' '+str(v) for k,v in item.items())
        if path=='data_source' and isinstance(item,dict):
            return str(item.get('location') or '未指定')+'（'+('允许下载' if item.get('download_allowed') is True else '未授权下载')+'）'
        if path=='inputs' and isinstance(item,dict):
            return '、'.join(str(v.get('type',k)) for k,v in item.items() if isinstance(v,dict)) or '未设置'
        if path=='output_schema' and isinstance(item,dict):
            props=item.get('properties') or {}
            return '、'.join(str(v.get('description') or k) for k,v in props.items() if isinstance(v,dict)) or '未设置'
        if isinstance(item,(dict,list)):return '内容有调整（高级详情可查看）'
        return str(item)
    lines=[]
    for change in review:
        path=change['path'];before=value(path,change['before']);after=value(path,change['after'])
        label=labels.get(path,'验收要求' if path.startswith('acceptance.') else path)
        if before==after:
            lines.append(label+'的具体约束有变化，请查看高级详情。')
        else:lines.append(label+'：'+before+' → '+after)
    return lines
