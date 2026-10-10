"""Bounded foreground supervision of one durable Training campaign."""
from datetime import datetime,timezone
import math
from pathlib import Path
import subprocess
import time
import uuid

from .campaign import advance,available
from .runner import atomic_json


def watch(session_provider,config_provider,root='runs/campaigns',run_store='runs/training-runs',steps=3,
          policy=None,research_rounds=None,campaign_id=None,duration=3600,poll_seconds=15,on_update=None):
    for name,value,minimum,maximum in [('duration',duration,1,86400),('poll_seconds',poll_seconds,5,60)]:
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
            raise ValueError(name+' outside supported bounds')
    started=time.monotonic();deadline=started+duration
    iterations=0;retries=0;consecutive_errors=0;state=None;reason='duration_elapsed';error=None
    started_at=datetime.now(timezone.utc).isoformat()
    def snapshot():
        return advance(session_provider(),config_provider(),root,run_store,steps,policy,'show',research_rounds,campaign_id)
    try:
        while time.monotonic()<deadline:
            iterations+=1
            try:
                state=advance(session_provider(),config_provider(),root,run_store,steps,policy,None,research_rounds,campaign_id)
                campaign_id=state['campaign_id'];consecutive_errors=0
            except (OSError,RuntimeError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as failure:
                error=type(failure).__name__+': '+str(failure)
                try:state=snapshot();campaign_id=state['campaign_id']
                except Exception:reason='state_unavailable';break
                kind=(state.get('intent') or {}).get('action',{}).get('kind')
                # Retry only observation of the same original job, never an LLM
                # call, training submission, resume, or arbitrary tool.
                transient=not isinstance(failure,(ValueError,TypeError,KeyError))
                if transient and kind in ('observe','logs','collect') and consecutive_errors<3:
                    consecutive_errors+=1;retries+=1
                else:reason='needs_attention';break
            if on_update:
                on_update({'campaign_id':campaign_id,'status':state['status'],'run_id':state.get('run_id'),
                           'remote_status_last_observed':state.get('run_status'),'paused':state.get('paused',False),
                           'elapsed_seconds':round(time.monotonic()-started,2),'observation_retry':consecutive_errors>0})
            if state.get('paused'):reason='paused';break
            if state.get('run_status')=='lost':reason='remote_worker_lost_reservation_retained';break
            if state['status'] in ('blocked','budget_exhausted','policy_stopped'):reason=state['status'];break
            if not state.get('intent') and not available(state):reason='no_pending_actions';break
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            if state['status'] not in ('waiting','action_uncertain'):continue
            time.sleep(min(poll_seconds,remaining))
    except KeyboardInterrupt:
        reason='interrupted'
        try:state=snapshot();campaign_id=state['campaign_id']
        except Exception:pass
    info={'started_at':started_at,'elapsed_seconds':time.monotonic()-started,'iterations':iterations,
          'observation_retries':retries,'stop_reason':reason,'remote_job_cancelled':False,
          'duration_semantics':'No new controller call after deadline; an in-flight bounded call may finish later.'}
    if error:info['last_observation_error']=error
    if state and Path(state['state_path']).is_file():
        folder=Path(state['state_path']).parent/'watch-runs';folder.mkdir(exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.json');atomic_json(path,info);info['report_path']=str(path.resolve())
    return dict(state or {'status':'watch_failed'},watch=info)
