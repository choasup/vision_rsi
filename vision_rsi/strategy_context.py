"""Bounded, task-neutral observations exposed to research strategies."""
import math


def finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)


def history_context(rows,version=3):
    if version not in (1,2,3):raise ValueError('Unsupported strategy context version')
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
    return result
