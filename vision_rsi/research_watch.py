"""Bounded foreground general-research supervision without automatic retries."""
import math
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid

from .runner import atomic_json


def watch(advance, inspect, turns=6, duration=3600, on_update=None):
    if type(turns) is not int or not 1 <= turns <= 1000:
        raise ValueError('research watch turns must be 1..1000')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 1 <= duration <= 86400:
        raise ValueError('research watch duration must be 1..86400 seconds')
    state=inspect()  # Missing or changed task bindings fail before any execution.
    directory=Path(state['directory'])
    started=time.monotonic();started_at=datetime.now(timezone.utc).isoformat()
    completed=0;reason='turn_limit_reached';error=None
    stop_states={'paused','no_objective','uncertain_api_request','planning_limit_exhausted'}
    try:
        for _ in range(turns):
            state=inspect()
            if state['research_status']['state'] in stop_states:
                reason=state['research_status']['state'];break
            if time.monotonic()-started >= duration:
                reason='duration_elapsed';break
            previous=state['events']
            result=advance()  # Exactly one bounded step; never retry this call.
            completed+=1
            state=inspect()
            if on_update:on_update(state)
            if state['events']==previous:
                reason='no_progress';break
            # Invalid model plans and failed tools need explicit attention.
            execution=result.get('execution',{})
            if execution.get('last_step_status') in ('planning_rejected','tool_failed'):
                reason=execution['last_step_status'];break
        else:
            if state['research_status']['state'] in stop_states:reason=state['research_status']['state']
    except KeyboardInterrupt:
        reason='interrupted'
    except Exception as failure:
        reason='needs_attention';error=type(failure).__name__
    # Re-read canonical records after interrupted/failed calls; no replay.
    try:
        state=inspect()
        if state['research_status']['state']=='paused':reason='paused'
    except Exception as failure:
        reason='state_unavailable';error=type(failure).__name__
    report={'started_at':started_at,'stop_reason':reason,'completed_steps':completed,'turn_limit':turns,
            'elapsed_seconds':time.monotonic()-started,'duration_seconds':duration,
            'duration_semantics':'No new step after deadline; an in-flight bounded call may finish later.',
            'automatic_retries':0,'background_process_started':False}
    if error:report['error_type']=error
    path=directory/'research-watch-runs'/(uuid.uuid4().hex+'.json')
    path.parent.mkdir(exist_ok=True)
    atomic_json(path,report)
    return dict(state,watch=dict(report,report_path=str(path.resolve())))
