"""Local research scheduling state; never infers live processes or task quality."""


def snapshot(events):
    controls = [e['kind'] for e in events if e['kind'] in ('paused', 'resumed')]
    requests = [e for e in events if e['payload'].get('record_type') == 'planning_request']
    budgets = [e for e in events if e['payload'].get('record_type') == 'planning_budget']
    limit = budgets[0]['payload']['max_planning_requests'] if budgets else 6
    responses = {e['payload']['request_key']: e for e in events
                 if e['payload'].get('record_type') == 'planning_response'}
    unsent = {e['payload']['request_key'] for e in events
              if e['payload'].get('record_type') == 'planning_not_dispatched'}
    uncertain = [e['key'] for e in requests if e['key'] not in responses and e['key'] not in unsent]
    consumed = {e['payload'].get('planning_response') for e in events
                if e['kind'] == 'action' or e['payload'].get('record_type') == 'planning_rejected'}
    cached = [e['key'] for e in responses.values() if e['key'] not in consumed]
    finished = {e['payload']['action'] for e in events if e['kind'] == 'result'}
    pending = [e['key'] for e in events if e['kind'] == 'action'
               and e['payload'].get('executor') == 'research-v1' and e['key'] not in finished]
    if not events: state = 'no_objective'
    elif controls and controls[-1] == 'paused': state = 'paused'
    elif pending: state = 'pending_action_recovery'
    elif uncertain: state = 'uncertain_api_request'
    elif cached: state = 'cached_response_available'
    elif len(requests) >= limit: state = 'planning_limit_exhausted'
    else: state = 'manual_step_available'
    return {'state': state, 'planning_limit': limit,
            'limit_source': 'frozen' if budgets else ('legacy' if requests else 'default_not_frozen'),
            'planning_attempts_used': len(requests), 'planning_attempts_remaining': max(0, limit-len(requests)),
            'known_not_dispatched_attempts': len(unsent), 'uncertain_requests': uncertain,
            'cached_responses': cached, 'pending_actions': pending,
            'live_process_verified': False, 'task_quality_verified': False,
            'autonomous_background_loop': False}
