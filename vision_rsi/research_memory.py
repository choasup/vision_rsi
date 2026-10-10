"""Read-only reconstruction and hash-bound retrieval of research observations."""
import hashlib
import json
from pathlib import Path
import re

from .runner import digest
from .strategy_context import encoded,history_context


def read_memory(session_id,campaign_id,root='runs/campaigns',source_index=None,context_sha256=None,history_rows=None):
    if not isinstance(session_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',session_id):raise ValueError('Invalid session ID')
    if not isinstance(campaign_id,str) or not re.fullmatch('[0-9a-f]{64}',campaign_id):raise ValueError('Invalid campaign ID')
    path=Path(root)/session_id/campaign_id/'state.json'
    raw=path.read_bytes();state=json.loads(raw)
    if state.get('campaign_id')!=campaign_id or digest(state['binding'])!=campaign_id or state['binding'].get('session_id')!=session_id:
        raise ValueError('Campaign memory identity changed')
    rows=state['history']
    count=len(rows) if history_rows is None else history_rows
    if type(count) is not int or not 0<=count<=len(rows):raise ValueError('Memory snapshot row count is outside retained history')
    full=history_context(rows[:count],3)
    checksum=hashlib.sha256(encoded(full)).hexdigest()
    if context_sha256 is not None and context_sha256!=checksum:raise ValueError('Research memory snapshot hash changed; no observation returned')
    result={'session_id':session_id,'campaign_id':campaign_id,'history_rows':count,'context_sha256':checksum,
            'state_sha256':hashlib.sha256(raw).hexdigest(),'read_only':True,'remote_polled':False,
            'scope':'Reconstructed v4 policy view; historical decisions retain their recorded context versions.'}
    if source_index is not None:
        if context_sha256 is None:raise ValueError('Original observation retrieval requires exact --context-sha256')
        if type(source_index) is not int or not 0<=source_index<count:raise ValueError('Memory source index outside snapshot')
        result.update(source_index=source_index,original_observation=full[source_index])
    else:
        view=history_context(rows[:count],4)
        result.update(strategy_context_version=4,view_rows=len(view),view=view)
    return result
