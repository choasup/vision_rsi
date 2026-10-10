"""Optional immutable per-campaign tool-attempt cap, derived from durable history."""
import math


def validate_limit(value):
    if type(value) is not int or not 0<=value<=100000:raise ValueError('controller.tool_attempt_limit must be an integer in 0..100000')
    return value


def configured_limit(config):
    if 'controller' not in config:return None
    controller=config['controller']
    if not isinstance(controller,dict) or set(controller)-{'tool_attempt_limit'}:raise ValueError('Unsupported controller configuration')
    return validate_limit(controller['tool_attempt_limit']) if 'tool_attempt_limit' in controller else None


def summary(state):
    if 'controller_budget_exhausted' in state and type(state['controller_budget_exhausted']) is not bool:raise ValueError('Invalid controller exhaustion flag')
    limit=state['binding'].get('controller_tool_attempt_limit')
    if 'controller_tool_attempt_limit' not in state['binding']:
        if state.get('controller_budget_exhausted'):raise ValueError('Unbound controller budget exhaustion record')
        return None
    validate_limit(limit)
    rows=list(state['history'])
    if state.get('intent'):rows.append(state['intent'])
    count=0
    for row in rows:
        attempts=row.get('tool_attempts')
        if not isinstance(attempts,list) or row.get('status')=='completed' and not attempts:raise ValueError('Controller attempt accounting missing')
        for attempt in attempts:
            if not isinstance(attempt,dict) or attempt.get('status') not in ('started','uncertain','completed','not_dispatched'):raise ValueError('Invalid controller attempt accounting')
            elapsed=attempt.get('elapsed_seconds')
            if elapsed is not None and (isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0):raise ValueError('Invalid controller attempt timing')
        if row.get('status')=='completed' and attempts[-1]['status']!='completed':raise ValueError('Completed controller action lacks completed attempt')
        count+=len(attempts)
    if count>limit:raise ValueError('Controller attempt accounting exceeds bound limit')
    if state.get('controller_budget_exhausted') and count!=limit:raise ValueError('Controller exhaustion record differs from attempt accounting')
    return {'limit':limit,'admitted_attempts':count,'remaining_attempts':limit-count,
            'scope':'This campaign only; includes started/uncertain/unsent attempts, not policy calls, GPU hours, tokens or billing.'}
