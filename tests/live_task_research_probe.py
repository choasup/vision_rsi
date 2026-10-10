"""One actual task-bound research CLI action, API cap 1; no candidate execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.ledger import Ledger
from vision_rsi.llm_usage import snapshot
from vision_rsi.runner import atomic_json,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--session-id',required=True)
    parser.add_argument('--config',default='config.local.json');parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--watch',action='store_true',help='Isolated task-bound foreground watch')
    parser.add_argument('--calls',type=int,choices=(1,2,3),default=1,help='Explicit planning/API cap; >1 requires --watch')
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    if args.calls>1 and not args.watch:parser.error('--calls >1 requires --watch')
    repo=Path(__file__).resolve().parents[1]
    original=json.loads(Path(args.config).read_text(encoding='utf-8'))
    name=original['llm']['api_key_env']
    if os.name=='nt' and not os.environ.get(name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            if isinstance(value,str):os.environ[name]=value
    folder=repo/'runs/task-research-live'/uuid.uuid4().hex;folder.mkdir(parents=True)
    print(str(folder),flush=True)
    llm={key:original['llm'][key] for key in ('model','base_url','api_key_env')}
    llm.update(usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=args.calls,response_format='json_object')
    config={'llm':llm,'remote':original['remote'],'research':{'allow_candidate_writes':False,'allow_candidate_checks':False}}
    if args.watch:config['research']['max_planning_requests']=args.calls
    atomic_json(folder/'config.json',config)
    database=Path(args.sessions)/'sessions.sqlite3'
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    research_root=folder/'research' if args.watch else repo/'runs/task-research'
    if args.watch:
        from vision_rsi.contracts import Sessions
        from vision_rsi.task_research import prepare
        prepare(Sessions(args.sessions,read_only=True).show(args.session_id),research_root)
    research=Ledger(research_root/args.session_id)
    old_keys={event['key'] for event in research.events()}
    argv=[sys.executable,'-X','utf8','-m','vision_rsi','training','research-watch' if args.watch else 'research-step','--session-id',args.session_id,
          '--sessions',str(Path(args.sessions).resolve()),'--config',str(folder/'config.json'),
          '--repository',str(repo),'--steps','1','--json']
    if args.watch:argv+=['--research-root',str(research_root),'--research-watch-turns',str(args.calls+1),'--watch-seconds','60']
    atomic_json(folder/'preregistered.json',{'session_id':args.session_id,'argv':argv,'api_call_limit':args.calls,
        'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'controller_source_sha256':hashlib.sha256((repo/'vision_rsi/controller.py').read_bytes()).hexdigest(),
        'candidate_writes':False,'candidate_checks':False,'gpu_allowed':False,'mode':'watch' if args.watch else 'step',
        'criteria':['CLI succeeds','each admitted request yields a completed read-only research action','exact frozen task contract in every request snapshot','session DB unchanged']+
                   (['clean JSON stdout','watch stops at frozen planning limit','persisted stop report','no automatic retries','later request includes prior completed tool result'] if args.watch else [])})
    completed=subprocess.run(argv,cwd=repo,capture_output=True,text=True,encoding='utf-8',timeout=100)
    (folder/'cli-output.txt').write_text(completed.stdout+'\n'+completed.stderr,encoding='utf-8')
    failure=None;passed=False
    try:
        assert completed.returncode==0
        if args.watch:
            structured=json.loads(completed.stdout)
            assert structured['watch']['stop_reason']=='planning_limit_exhausted'
            assert structured['watch']['completed_steps']==args.calls
            assert structured['watch']['automatic_retries']==0
            report=json.loads(Path(structured['watch']['report_path']).read_text(encoding='utf-8'))
            assert report['stop_reason']==structured['watch']['stop_reason']
        records=[event for event in research.events() if event['key'] not in old_keys]
        requests=[event for event in records if event['payload'].get('record_type')=='planning_request']
        results=[event for event in records if event['kind']=='result']
        assert len(requests)==len(results)==args.calls
        raw=(research.directory/'contract.json').read_bytes()
        for index,event in enumerate(requests):
            request=event['payload']
            assert request['request_snapshot_sha256']==digest(request['request_snapshot'])
            prompt=json.loads(request['request_snapshot']['messages'][0]['content'])
            assert prompt['frozen_task_contract']['sha256']==hashlib.sha256(raw).hexdigest()
            assert prompt['frozen_task_contract']['contract']==json.loads(raw)
            if args.watch:
                assert prompt['planning_budget']['limit']==args.calls
                assert prompt['planning_budget']['attempts_used']==index
                assert prompt['task_readiness']['session_id']==args.session_id
            if index:
                prior=results[index-1]
                assert prior['seq']<event['seq']
                assert any(row['key']==prior['key'] and row['kind']=='result' for row in prompt['history'])
        for result in results:
            assert result['payload']['status']=='completed'
            action=next(event for event in records if event['key']==result['payload']['action'])
            assert action['payload']['tool'] in ('inspect_repository','remote_environment','read_source','synthesize')
            assert result['payload']['read_only'] is True
        assert hashlib.sha256(database.read_bytes()).hexdigest()==before
        passed=True
    except Exception as error:failure=type(error).__name__+': '+str(error)[:500]
    usage=snapshot(str(folder/'usage.sqlite3')) if (folder/'usage.sqlite3').exists() else None
    passed=passed and usage is not None and usage['calls']==args.calls
    evidence={'directory':str(folder),'passed':passed,'failure':failure,'cli_returncode':completed.returncode,
              'usage':usage,'gpu_used':False,'training_performed':False,
              'mode':'watch' if args.watch else 'step',
              'scope':'Bounded task-bound read-only planning/inspection sequence; no autonomous quality or RSI gain proof'}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
