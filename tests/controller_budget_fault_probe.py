"""Actual process-exit probe for a one-attempt fixture campaign, no remote/LLM/GPU."""
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
from vision_rsi.controller_budget import summary
from vision_rsi.runner import atomic_json

SESSION={'session_id':'budget-fault-fixture','task_id':'fixture','versions':[{'version':1,'contract':{}}]}
CONFIG={'remote':{'ssh_host':'fixture-not-contacted','workspace':'/fixture'},'controller':{'tool_attempt_limit':1}}


def phase(folder,name):
    scope=(SESSION,CONFIG,folder/'campaigns',folder/'runs')
    if name=='crash':
        def interrupt(*args):
            result=execute(*args)
            atomic_json(folder/'result-before-exit.json',result)
            os._exit(73)
        with patch('vision_rsi.campaign.execute',side_effect=interrupt):advance(*scope,steps=1)
        raise AssertionError('Expected actual process exit')
    if name=='explicit-resume':
        state=advance(*scope,control='resume')
    else:
        with patch('vision_rsi.campaign.execute',side_effect=AssertionError('No free tool retry after exhausted reservation')),patch('vision_rsi.campaign.choose',side_effect=AssertionError('No new decision after exhausted reservation')):
            state=advance(*scope,steps=10)
        assert state['status']=='controller_budget_exhausted'
    assert state['controller_tool_budget']['admitted_attempts']==1
    assert len(state['intent']['tool_attempts'])==1
    atomic_json(folder/(name+'-state.json'),state)


def probe(root):
    folder=root.resolve()/('budget-fault-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--folder',str(folder)]
    def child(name,expected=0):
        result=subprocess.run(command+['--phase',name],capture_output=True,text=True,timeout=30)
        assert result.returncode==expected,result.stderr
        return result.returncode
    crash=child('crash',73)
    path=next((folder/'campaigns').glob('*/*/state.json'))
    pending=json.loads(path.read_text(encoding='utf-8'));intent=pending['intent']
    assert pending['history']==[] and intent['action']['kind']=='prepare'
    assert [a['status'] for a in intent['tool_attempts']]==['started']
    assert summary(pending)['remaining_attempts']==0
    receipt=json.loads((folder/'result-before-exit.json').read_text(encoding='utf-8'))
    assert receipt['training_performed'] is False and receipt['status']=='blocked'
    child('resume');child('explicit-resume');child('resume')
    final=json.loads(path.read_text(encoding='utf-8'))
    assert final['intent']==intent and final['history']==[]
    assert summary(final)['admitted_attempts']==1 and not final.get('run_id')
    evidence={'fixture':True,'directory':str(folder),'crash_exit':crash,'independent_processes':4,
              'tool_attempt_limit':1,'admitted_attempts':1,'remaining_attempts':0,'pending_attempt_status':'started',
              'intent_retained_exactly':True,'completed_actions_added':0,'no_free_retry':True,'os_lock_released':True,
              'explicit_resume_did_not_refresh_limit':True,'result_before_exit_status':receipt['status'],
              'run_created':False,'remote_called':False,'llm_called':False,'gpu_used':False,
              'scope':'Actual abrupt exit after local prepare result before state projection; not power loss, GPU interruption or unified cost accounting.'}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='runs/resource-bootstrap');parser.add_argument('--folder');parser.add_argument('--phase',choices=['crash','resume','explicit-resume']);args=parser.parse_args()
    if args.phase:
        if not args.folder:parser.error('--folder required for child phase')
        phase(Path(args.folder),args.phase)
    else:probe(Path(args.root))

