"""Replay recorded decisions without running candidate code or creating stores."""
import base64
import hashlib
import json
from pathlib import Path

from .campaign import available, project
from .candidates import verify_candidate
from .runner import digest
from .strategy_protocol import validate_decision


def verify_trace(state):
    policy=state['binding'].get('policy')
    record=None
    if policy:
        folder=Path(policy['store']).resolve()/policy['candidate_id']
        record=verify_candidate(folder.parent,json.loads((folder/'candidate.json').read_text(encoding='utf-8')))
        names=set(record['source_hashes'])|{'vision_rsi/research.py'}
        files={name:(Path(record['checkout'])/name).read_bytes() for name in sorted(names)}
        source_hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    def verify_decision_evidence(row,actions,history):
        decision=row['decision']
        if policy:
            path=Path(row['policy_evidence']).resolve()
            if path.parent!=(folder/'checks').resolve() or not path.name.endswith('.protocol.json'):
                raise ValueError('Policy evidence outside frozen candidate checks')
            report=json.loads(path.read_text(encoding='utf-8'))
            if report['candidate_id']!=record['candidate_id'] or report['git_revision']!=record['git_revision']:
                raise ValueError('Policy evidence uses another candidate')
            if report['status']!='protocol_passed' or report['protocol_failures']:
                raise ValueError('Policy did not pass protocol')
            if report['protocol_source_sha256']!=row['control_sources']['strategy_protocol.py']:
                raise ValueError('Protocol source differs from execution trace')
            cases=report['cases']
            if len(cases)!=1:raise ValueError('Expected exactly one controller decision')
            case=cases[0];budget=case['budget']
            if isinstance(budget,bool) or not isinstance(budget,int) or not 1<=budget<=10:
                raise ValueError('Invalid controller decision budget')
            if case['history']!=history or case['actions']!=actions:
                raise ValueError('Policy context differs from replayed controller state')
            request={'files':{name:base64.b64encode(raw).decode() for name,raw in files.items()},
                     'source_hashes':source_hashes,'module':policy['module'],'function':'propose','cases':cases}
            if digest(request)!=report['request_sha256']:raise ValueError('Policy request identity changed')
            if report['response']['source_hashes']!=source_hashes or report['response']['observation']['results']!=[decision]:
                raise ValueError('Executed policy output differs from recorded decision')
            validate_decision(history,actions,budget,decision)
        elif decision!={'action_id':actions[0]['id'],'rationale':'Deterministic baseline control order'}:
            raise ValueError('Baseline decision differs from fixed controller order')

    replay={'history':[],'research_rounds':state['binding'].get('research_rounds',0)}
    for row in state['history']:
        actions=available(replay)
        if row.get('status')!='completed' or row['action'] not in actions:
            raise ValueError('Action does not match replayed controller state')
        decision=row['decision']
        if decision['action_id']!=row['action']['id']:raise ValueError('Executed action differs from policy decision')
        history=[{'id':item['action']['id'],'kind':item['action']['kind'],'status':item['status']} for item in replay['history']]
        verify_decision_evidence(row,actions,history)
        project(replay,row['action'],row['result'])
        replay['history'].append(row)
    stop=state.get('policy_stop')
    if stop:
        if state.get('intent') or state.get('status')!='policy_stopped' or stop['decision'].get('action_id') is not None:
            raise ValueError('Invalid terminal policy stop')
        history=[{'id':item['action']['id'],'kind':item['action']['kind'],'status':item['status']} for item in replay['history']]
        actions=available(replay)
        if not actions:raise ValueError('Policy stop has no decision context')
        verify_decision_evidence(stop,actions,history)
    elif state.get('status')=='policy_stopped':raise ValueError('Terminal policy stop evidence missing')
    for key in ('plan','run_id','run_status','receipt_collected','analysis','proposals_attempted','research_stopped'):
        if state.get(key)!=replay.get(key):raise ValueError('Campaign projection differs from decision replay: '+key)
    if not state.get('intent') and not stop and state.get('status')!=replay.get('status'):
        raise ValueError('Campaign status differs from decision replay')
    if not replay['history'] and not stop:raise ValueError('No completed decisions to verify')
    return {'verified':True,'decisions_verified':len(replay['history'])+bool(stop),
            'candidate_id':record['candidate_id'] if record else None}
