"""Deterministic detection of changes to an established task definition."""
import copy
import json


def changes(previous,proposed):
    if not isinstance(previous,dict) or not isinstance(proposed,dict):return []
    result=[]
    def compare(path,before,after):
        if json.dumps(before,sort_keys=True,allow_nan=False)!=json.dumps(after,sort_keys=True,allow_nan=False):
            result.append({'path':path,'before':copy.deepcopy(before),'after':copy.deepcopy(after)})
    if previous.get('goal'):
        compare('goal',previous['goal'],proposed.get('goal'))
    for key in ('inputs','output_schema'):
        if previous.get(key):compare(key,previous[key],proposed.get(key))
    old=previous.get('acceptance') or {};new=proposed.get('acceptance') or {}
    if isinstance(old,dict):
        for key,value in old.items():
            if value is not None and value!='':compare('acceptance.'+key,value,new.get(key) if isinstance(new,dict) else None)
    # Once a task exists, a model cannot create or alter resource authorization.
    if previous.get('budget') or proposed.get('budget'):compare('budget',previous.get('budget'),proposed.get('budget'))
    return result
