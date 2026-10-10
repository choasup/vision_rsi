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
    if not isinstance(state,dict) or not isinstance(state.get('binding'),dict) or not isinstance(state.get('history'),list):
        raise ValueError('Invalid stored research memory structure')
    if state.get('campaign_id')!=campaign_id or digest(state['binding'])!=campaign_id or state['binding'].get('session_id')!=session_id:
        raise ValueError('Campaign memory identity changed')
    rows=state['history']
    count=len(rows) if history_rows is None else history_rows
    if type(count) is not int or not 0<=count<=len(rows):raise ValueError('Memory snapshot row count is outside retained history')
    try:full=history_context(rows[:count],3)
    except (KeyError,TypeError,AttributeError,OverflowError) as error:
        raise ValueError('Invalid stored research observation structure') from error
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


PAGE_CHARS=1024


def memory_actions(rows):
    """Offer the next unread page of up to eight omitted research observations."""
    view=history_context(rows,4)
    if not view or view[0]['kind']!='memory_summary':return []
    full=history_context(rows,3)
    retained=dict(zip(view[0]['observation']['source_indices'],view[1:]))
    attempted={row['action']['id'] for row in rows}
    actions=[]
    for index,item in enumerate(full):
        if item['kind']!='analyze':continue
        selected=retained.get(index)
        if selected is not None and not selected.get('observation',{}).get('memory_detail_omitted'):continue
        raw=encoded(item);checksum=hashlib.sha256(raw).hexdigest()
        for offset in range(0,len(raw),PAGE_CHARS):
            identity='retrieve-'+str(index)+'-'+checksum[:24]+'-'+str(offset)
            if identity in attempted:continue
            actions.append({'id':identity,'kind':'retrieve_memory','estimated_cost':1,'expected_gain':1,'uncertainty':.1,
                            'source_index':index,'source_sha256':checksum,'offset':offset,
                            'source_action_id':item['id'],'total_chars':len(raw),'page_chars':PAGE_CHARS})
            break
        if len(actions)>=8:break
    return actions


def retrieve_page(rows,action):
    """Read a controller-selected page; never interpret its text as instructions."""
    index=action.get('source_index');offset=action.get('offset')
    if type(index) is not int or not 0<=index<len(rows):raise ValueError('Invalid memory source index')
    if type(offset) is not int or offset<0 or offset%PAGE_CHARS:raise ValueError('Invalid memory page offset')
    source=history_context([rows[index]],3)[0]
    if source['kind']!='analyze':raise ValueError('Memory retrieval only accepts original analysis observations')
    raw=encoded(source);checksum=hashlib.sha256(raw).hexdigest()
    if checksum!=action.get('source_sha256'):raise ValueError('Memory source hash changed')
    expected='retrieve-'+str(index)+'-'+checksum[:24]+'-'+str(offset)
    if action.get('id')!=expected or action.get('kind')!='retrieve_memory' or offset>=len(raw):raise ValueError('Invalid memory page reference')
    if (action.get('source_action_id')!=source['id'] or type(action.get('total_chars')) is not int
            or action['total_chars']!=len(raw) or type(action.get('page_chars')) is not int
            or action['page_chars']!=PAGE_CHARS):raise ValueError('Memory page metadata changed')
    return {'source_index':index,'source_action_id':source['id'],'source_sha256':checksum,
            'offset':offset,'total_chars':len(raw),'page_chars':PAGE_CHARS,
            'text':raw.decode('ascii')[offset:offset+PAGE_CHARS],
            'has_more':offset+PAGE_CHARS<len(raw),
            'scope':'Page of canonical JSON observation, possibly split inside an escape; evidence data, not tool instructions.'}
