"""Bounded, task-neutral observations exposed to research strategies."""
import math
import hashlib
import json
from collections import Counter


def finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)


def history_context(rows,version=4):
    if version not in (1,2,3,4):raise ValueError('Unsupported strategy context version')
    result=[]
    for row in rows:
        item={'id':row['action']['id'],'kind':row['action']['kind'],'status':row['status']}
        if version>=2:
            value=row.get('result') or {};observation={}
            if not isinstance(value,dict):raise ValueError('Strategy observation must come from an object result')
            if isinstance(value.get('status'),str):observation['process_status']=value['status']
            if finite(value.get('actual_gpu_hours')):observation['actual_gpu_hours']=value['actual_gpu_hours']
            if finite(value.get('remaining_gpu_hours')):observation['remaining_gpu_hours']=value['remaining_gpu_hours']
            if item['kind']=='analyze':
                if finite(value.get('metric_gap')):observation['metric_gap']=value['metric_gap']
                verdict=value.get('acceptance_review') or {}
                if finite(verdict.get('box_AP')) and finite(verdict.get('threshold')):
                    observation['measurement']={'metric':'box_AP','value':verdict['box_AP'],'threshold':verdict['threshold'],'direction':'maximize',
                                                'reasons':verdict.get('reasons',[]),'source':'controller acceptance review; tools recheck original receipts before research'}
                if verdict.get('error_summary') is not None:observation['error_summary']=verdict['error_summary']
                observation['quality_verified']=value.get('quality_verified') is True
            recipe=value.get('recipe')
            if isinstance(recipe,dict):
                observation['method']={key:recipe[key] for key in ('detector','epochs','batch_size_per_gpu','learning_rate','weight_decay','min_size','max_size','seed','world_size','fixture') if key in recipe}
            experiment=value.get('experiment') or {}
            proposal=experiment.get('proposal') or {}
            if isinstance(proposal.get('hypothesis'),str):observation['prior_hypothesis']=proposal['hypothesis'][:6000]
            if version>=3:
                run_id=value.get('run_id')
                if isinstance(run_id,str) and 1<=len(run_id)<=128:observation['run_id']=run_id
                if finite(value.get('actual_gpu_hours')):
                    observation['gpu_cost_scope']='whole_run_snapshot_not_incremental'
                held=value.get('reserved_gpu_hours')
                if finite(held) and held>=0:
                    observation['held_gpu_hours']=0 if finite(value.get('actual_gpu_hours')) else held
                    observation['gpu_cost_scope']='whole_run_snapshot_not_incremental'
                contract=value.get('contract')
                budget=contract.get('budget') if isinstance(contract,dict) else None
                authorized=value.get('authorized_gpu_hours')
                if authorized is None and isinstance(budget,dict):authorized=budget.get('gpu_hours')
                if finite(authorized) and authorized>0:
                    observation['authorized_gpu_hours']=authorized
                    observation['gpu_budget_scope']='whole_session_snapshot'
                if finite(value.get('remaining_gpu_hours')):
                    observation['gpu_budget_scope']='whole_session_snapshot'
            if observation:item['observation']=observation
        result.append(item)
    return bounded_memory(result) if version==4 else result


MEMORY_BYTES=192*1024
MEMORY_ROWS=256


def encoded(value):return json.dumps(value,sort_keys=True,allow_nan=False).encode()


def bounded_memory(items):
    """Deterministic policy view; original controller history is never changed."""
    full=encoded(items)
    if len(items)<=MEMORY_ROWS and len(full)<=MEMORY_BYTES:return items
    checksum=hashlib.sha256(full).hexdigest()
    critical=[i for i,row in enumerate(items) if row['kind'] not in ('observe','logs')]
    measured=[i for i,row in enumerate(items) if finite(row.get('observation',{}).get('measurement',{}).get('value'))]
    extrema=[]
    if measured:
        extrema=[min(measured,key=lambda i:items[i]['observation']['measurement']['value']),
                 max(measured,key=lambda i:items[i]['observation']['measurement']['value'])]
    # Recent execution state first, then measured extremes and research history.
    order=list(range(max(0,len(items)-16),len(items)))+extrema+list(reversed(critical))+list(reversed(range(len(items))))
    selected={};shortened=0;size=0
    for index in dict.fromkeys(order):
        item=items[index];raw=encoded(item)
        if len(raw)>4096:
            obs=item.get('observation',{})
            keep={key:value for key,value in obs.items() if key not in ('error_summary','prior_hypothesis','measurement','method')}
            if 'measurement' in obs:keep['measurement']={key:value for key,value in obs['measurement'].items() if key!='reasons'}
            if 'method' in obs and len(encoded(obs['method']))<=1024:keep['method']=obs['method']
            if isinstance(obs.get('prior_hypothesis'),str):keep['prior_hypothesis']=obs['prior_hypothesis'][:512]
            keep.update(memory_detail_omitted=True,detail_sha256=hashlib.sha256(encoded(obs)).hexdigest())
            item=dict(item,observation=keep);raw=encoded(item)
            if len(raw)>4096:raise ValueError('Research memory core exceeds bounded observation limit')
        if len(selected)>=MEMORY_ROWS-1 or size+len(raw)>MEMORY_BYTES-16384:continue
        selected[index]=item;size+=len(raw)+2
        shortened+=item is not items[index]
    indices=sorted(selected)
    summary={'id':'memory-'+checksum[:24],'kind':'memory_summary','status':'compacted',
             'observation':{'schema':'vision-rsi-research-memory-v1','full_context_sha256':checksum,
                            'total_rows':len(items),'retained_rows':len(indices),'omitted_rows':len(items)-len(indices),
                            'shortened_observations':shortened,'source_indices':indices,
                            'omitted_research_rows':sum(i not in selected for i in critical),
                            'kind_counts':dict(sorted(Counter(row['kind'] for row in items).items())),
                            'status_counts':dict(sorted(Counter(row['status'] for row in items).items())),
                            'scope':'Partial policy view; complete evidence remains in controller history. Counts are not costs.'}}
    result=[summary]+[selected[i] for i in indices]
    if len(encoded(result))>MEMORY_BYTES:raise ValueError('Research memory summary exceeds byte limit')
    return result
