"""Real local process-exit probe using synthetic history, no remote/LLM/GPU."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.campaign import advance,execute
from vision_rsi.research_memory import memory_actions
from vision_rsi.runner import atomic_json

SESSION={'session_id':'memory-fault-fixture','task_id':'fixture','versions':[{'contract':{}}]}
CONFIG={'remote':{'ssh_host':'fixture-not-contacted','workspace':'/fixture'}}


def choose_memory(state,actions,*args):
    action=next(a for a in actions if a['kind']=='retrieve_memory')
    return {'action_id':action['id'],'rationale':'Synthetic process-exit probe'},None


def run_phase(folder,phase):
    if phase=='crash':
        def interrupt(*args):
            result=execute(*args)
            atomic_json(folder/'read-before-exit.json',result)
            os._exit(73)
        with patch('vision_rsi.campaign.choose',side_effect=choose_memory),patch('vision_rsi.campaign.execute',side_effect=interrupt):
            advance(SESSION,CONFIG,folder/'campaigns',folder/'runs',steps=1,research_rounds=1)
        raise AssertionError('Expected actual process exit')
    with patch('vision_rsi.campaign.choose',side_effect=AssertionError('Pending read must not choose again')):
        state=advance(SESSION,CONFIG,folder/'campaigns',folder/'runs',steps=1,research_rounds=1)
    atomic_json(folder/'resumed-state.json',state)


def probe(root):
    folder=root.resolve()/('memory-fault-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    with patch('vision_rsi.campaign.prepare',return_value={'status':'blocked','blockers':['fixture']}):
        initial=advance(SESSION,CONFIG,folder/'campaigns',folder/'runs',steps=1,research_rounds=1)
    path=Path(initial['state_path']);state=json.loads(path.read_text(encoding='utf-8'))
    history=[{'action':{'id':'observe-'+str(i),'kind':'observe'},'status':'completed','result':{}} for i in range(1000)]
    history[10]={'action':{'id':'analyze-10','kind':'analyze'},'status':'completed','result':{'acceptance_review':{'box_AP':40,'threshold':60,'error_summary':{'detail':'fixture '*3000}}}}
    state.update(history=history,plan={'status':'ready_to_submit'},run_id='fixture',run_status='completed',receipt_collected=True,analysis={'quality_verified':False},status='needs_research')
    atomic_json(path,state)
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--folder',str(folder)]
    crash=subprocess.run(command+['--phase','crash'],capture_output=True,text=True,timeout=30)
    assert crash.returncode==73,crash.stderr
    pending=json.loads(path.read_text(encoding='utf-8'))
    assert pending['history']==history and pending['intent']['action']['offset']==0
    assert pending['intent']['tool_attempts'][-1]['status']=='started'
    resumed=subprocess.run(command+['--phase','resume'],capture_output=True,text=True,timeout=30)
    assert resumed.returncode==0,resumed.stderr
    final=json.loads(path.read_text(encoding='utf-8'));row=final['history'][-1]
    assert final['intent'] is None and len(final['history'])==len(history)+1
    assert row['result']==json.loads((folder/'read-before-exit.json').read_text(encoding='utf-8'))
    assert [a['status'] for a in row['tool_attempts']]==['started','completed']
    assert memory_actions(final['history'])[0]['offset']==1024
    evidence={'fixture':True,'directory':str(folder),'crash_exit':crash.returncode,'resume_exit':resumed.returncode,
              'os_lock_released':True,'same_page_result':True,'completed_pages_added':1,'next_offset':1024,
              'attempt_statuses':['started','completed'],'remote_called':False,'llm_called':False,'gpu_used':False,
              'scope':'Actual abrupt local process exit after read before result persistence, not power loss or real research efficiency.'}
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='runs/resource-bootstrap');parser.add_argument('--folder');parser.add_argument('--phase',choices=['crash','resume']);args=parser.parse_args()
    if args.phase:
        if not args.folder:parser.error('--folder required for child phase')
        run_phase(Path(args.folder),args.phase)
    else:probe(Path(args.root))
