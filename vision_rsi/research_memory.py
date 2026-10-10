"""Deterministic metric memory derived from recorded tool evidence."""
import math
from .runner import digest


def metric_memory(events):
    actions={e['key'] for e in events if e['kind']=='action' and e['payload'].get('tool')=='evaluate_contract'}
    groups={};count=0
    fields=('contract_sha256','dataset_sha256','evaluator_sha256','gate_sha256')
    for index,event in enumerate(events):
        payload=event['payload'];value=payload.get('observation')
        if event['kind']!='result' or payload.get('status')!='completed' or payload.get('action') not in actions or not isinstance(value,dict):continue
        metric=value.get('metric_report');identity=value.get('evaluation_identity')
        if not isinstance(metric,dict) or not isinstance(identity,dict) or any(not isinstance(identity.get(k),str) or len(identity[k])!=64 for k in fields):continue
        if not isinstance(event['key'],str) or len(event['key'])>256:continue
        if any(value.get(k) is not None and (not isinstance(value[k],str) or len(value[k])>64) for k in ('candidate_id','report_sha256')):continue
        score=metric.get('event_micro_f1')
        if type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1:continue
        binding={key:identity[key] for key in fields};key=digest(binding)
        group=groups.setdefault(key,{'comparison_binding':binding,'best':None,'latest':None,'latest_failure':None,'last_index':index})
        row={'ref':event['key'],'candidate_id':value.get('candidate_id'),'report_sha256':value.get('report_sha256'),
             'observation_sha256':digest(value),'event_micro_f1':score,
             'threshold':metric.get('threshold'),'metric_threshold_met':metric.get('metric_threshold_met'),
             'tp':metric.get('tp'),'fp':metric.get('fp'),'fn':metric.get('fn')}
        if group['best'] is None or score>group['best']['event_micro_f1']:group['best']=row
        group['latest']=row;group['last_index']=index
        if metric.get('metric_threshold_met') is False:group['latest_failure']=row
        count+=1
    ordered=sorted(groups.values(),key=lambda group:group['last_index'],reverse=True)
    selected=[{key:value for key,value in group.items() if key!='last_index'} for group in ordered[:2]]
    return {'scope':'Recorded development metrics; compare only within identical bindings. Not production or RSI acceptance.',
            'evaluation_count':count,'comparison_group_count':len(groups),'groups':selected,
            'omitted_group_count':max(0,len(groups)-len(selected)),'selection':'two most recently evaluated groups; best, latest and latest failure',
            'quality_verified':False,'agent_adopted':False}
