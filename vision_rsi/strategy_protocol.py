"""Deterministic boundary between proposed strategy decisions and execution."""
import math


def number(value,name,minimum=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid '+name)
    if minimum is not None and value<minimum:raise ValueError('Invalid '+name)
    return value


def validate_context(history,actions,budget):
    number(budget,'budget',0)
    if not isinstance(history,list) or not isinstance(actions,list):raise ValueError('History and actions must be arrays')
    if len(history)>10000 or len(actions)>1000:raise ValueError('Strategy context exceeds bounds')
    seen=set()
    for row in history+actions:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not 1<=len(row['id'])<=128:raise ValueError('Invalid action ID')
    for action in actions:
        if action['id'] in seen:raise ValueError('Duplicate candidate action ID')
        seen.add(action['id'])
        if number(action.get('estimated_cost'),'estimated cost',0)==0:raise ValueError('Action cost must include a positive reservation')
        number(action.get('expected_gain'),'expected gain')
        number(action.get('uncertainty'),'uncertainty',0)
    return True


def validate_decision(history,actions,budget,decision):
    validate_context(history,actions,budget)
    if not isinstance(decision,dict):raise ValueError('Strategy decision must be an object')
    rationale=decision.get('rationale')
    if not isinstance(rationale,str) or not 1<=len(rationale)<=4000:raise ValueError('Decision needs bounded rationale')
    action_id=decision.get('action_id')
    if action_id is None:return decision
    if not isinstance(action_id,str):raise ValueError('Invalid selected action ID')
    if action_id in {row['id'] for row in history}:raise ValueError('Strategy selected an already attempted action; retries require a new explicit attempt ID')
    selected=next((action for action in actions if action['id']==action_id),None)
    if selected is None:raise ValueError('Strategy invented an unavailable action')
    if selected['estimated_cost']>budget:raise ValueError('Strategy selected an unaffordable action')
    return decision
