"""Bounded real remote CPU fixture executions; no learned-model acceptance claim."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.bundle_acceptance import accept
from vision_rsi.candidate_bundle import verify, run
from vision_rsi.runner import atomic_json
import vision_rsi.remote as transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true');parser.add_argument('--bundle',required=True)
    parser.add_argument('--task-scoped',action='store_true',help='Also verify task registry reservation and cached Training CLI')
    parser.add_argument('--serving-check',action='store_true',help='Add two fresh serving checks; requires task-scoped')
    parser.add_argument('--config',default='config.local.json');args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; two CPU calls or four with serving-check, no LLM/GPU')
    if args.serving_check and not args.task_scoped:parser.error('--serving-check requires --task-scoped')
    bundle=verify(args.bundle)
    contract=json.loads(base64.b64decode(bundle['contract_base64']))
    remote=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))['remote']
    root=Path(__file__).resolve().parents[1]/'runs/bundle-acceptance-live'/uuid.uuid4().hex
    root.mkdir(parents=True);print(str(root),flush=True)
    samples=[]
    for split in ('development','holdout'):
        sample=json.loads(json.dumps(contract['example_input']));sample['sample_id']=split
        for name,value in sample['inputs'].items():
            for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                filename=split+'-'+name+str(index)+'.bin';item['uri']=filename
                content=(b'P6\n1 1\n255\n'+bytes([index,0,255 if split=='development' else 254])) if name=='views' else (split+' raw nondecoded video fixture').encode()
                (root/filename).write_bytes(content)
        samples.append(sample)
    event={'label':'action','start_seconds':0,'end_seconds':1}
    dataset=root/'holdout.json';atomic_json(dataset,{'purpose':'independent_acceptance','samples':[samples[1]],
        'ground_truth':{'labels':['action'],'samples':[{'sample_id':'holdout','events':[event]}]}})
    atomic_json(root/'preregistered.json',{'scope':__doc__,'bundle_id':bundle['bundle_id'],'expected_remote_calls':4 if args.serving_check else 2,
        'developer_serving_target_seconds':30 if args.serving_check else None,
        'expected_fixture_f1':1,'llm_calls':0,'gpu_used':False,'quality_verified':False,
        'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    calls=[];original=transport.check_candidate;passed=False;failure=None;result=None;registry=None;cli_verified=False;serving=None;serving_cli_verified=False
    def counted(*values):calls.append(True);return original(*values)
    transport.check_candidate=counted
    try:
        development=run(args.bundle,[samples[0]],remote,root/'development',media_directory=root)
        values=(args.bundle,dataset,[development['execution_path']],remote,root/'acceptance')
        operation=accept
        if args.task_scoped:
            from vision_rsi.capability import Capabilities
            from vision_rsi.contracts import Sessions
            from vision_rsi.task_acceptance import accept as task_accept
            sessions=Sessions(root/'sessions')
            session=sessions.create('acceptance-fixture','Explicit developer fixture only; no model quality claim')
            session=sessions.define(session['session_id'],contract)
            registry=Capabilities(root/'registry');delivery=registry.register_candidate(session,args.bundle)
            operation=task_accept;values=(registry,session,delivery['version'],dataset,[development['execution_path']],remote)
        result=operation(*values)
        assert result['status']=='holdout_metric_met' and result['metric_report']['event_micro_f1']==1
        assert operation(*values)==result and len(calls)==2
        assert not result['production_accepted'] and not result['complete_development_history_verified']
        if args.task_scoped:
            import subprocess
            command=[sys.executable,'-X','utf8','-m','vision_rsi','training','accept-candidate',
                '--session-id',session['session_id'],'--sessions',str(root/'sessions'),'--registry',str(root/'registry'),
                '--version',delivery['version'],'--dataset',str(dataset),'--development',development['execution_path'],
                '--config',str(Path(args.config).resolve()),'--json']
            completed=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert completed.returncode==0,completed.stderr
            assert json.loads(completed.stdout)==result
            cli_verified=True
        if args.serving_check:
            from vision_rsi.candidate_serving import check
            serving=check(registry,session,delivery['version'],dataset,remote,30)
            assert serving['status']=='serving_contract_checks_met'
            assert serving['selected_runtime_consistent'] and not serving['environment_fully_verified']
            assert check(registry,session,delivery['version'],dataset,remote,30)==serving and len(calls)==4
            command=[sys.executable,'-X','utf8','-m','vision_rsi','training','candidate-serving-check',
                '--session-id',session['session_id'],'--sessions',str(root/'sessions'),'--registry',str(root/'registry'),
                '--version',delivery['version'],'--dataset',str(dataset),'--max-latency-seconds','30',
                '--config',str(Path(args.config).resolve()),'--json']
            completed=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert completed.returncode==0,completed.stderr
            assert json.loads(completed.stdout)==serving
            serving_cli_verified=True
        passed=True
    except Exception as error:failure=type(error).__name__+': '+str(error)[:500]
    finally:
        transport.check_candidate=original
        if registry is not None:registry.close()
    evidence={'passed':passed,'failure':failure,'remote_calls':len(calls),'result':result,
        'gpu_used':False,'llm_calls':0,'quality_verified':False,'scope':__doc__,'task_scoped':args.task_scoped,'cached_cli_verified':cli_verified,
        'serving':serving,'serving_cli_verified':serving_cli_verified}
    atomic_json(root/'evidence.json',evidence);print(json.dumps(evidence,ensure_ascii=False,indent=2));return int(not passed)


if __name__=='__main__':raise SystemExit(main())
