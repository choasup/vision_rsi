"""One real planner request plus one CPU media-bundle evaluation; no model quality claim."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.candidates import Candidates
from vision_rsi.controller import execute,research_step
from vision_rsi.ledger import Ledger
from vision_rsi.llm_usage import snapshot
from vision_rsi.runner import atomic_json
from vision_rsi.event_eval import PROTOCOL
import vision_rsi.remote as transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live:parser.error('--live required; at most one paid planning request, no GPU')
    repo=Path(__file__).resolve().parents[1];original=json.loads(Path(args.config).read_text(encoding='utf-8'))
    folder=repo/'runs/controller-bundle-live'/uuid.uuid4().hex;folder.mkdir(parents=True);print(str(folder),flush=True)
    contract=json.loads((repo/'examples/interface-contract.json').read_text())
    contract['goal']='Developer media execution fixture only; no learned visual model'
    event={'label':'action','start_seconds':0,'end_seconds':1}
    contract['acceptance']={'metric':'event_micro_f1','direction':'maximize','evaluation_protocol':PROTOCOL,'iou_threshold':.5,'threshold':.95}
    contract['output_schema']={'type':'object','properties':{'events':{'type':'array','items':{'type':'object',
        'properties':{'label':{'type':'string'},'start_seconds':{'type':'number'},'end_seconds':{'type':'number'}},
        'required':['label','start_seconds','end_seconds'],'additionalProperties':False}}},'required':['events'],'additionalProperties':False}
    contract['example_output']={'events':[event]};sample=json.loads(json.dumps(contract['example_input']))
    for field,value in sample['inputs'].items():
        for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
            name=field+str(index)+'.bin';item['uri']=name
            (folder/name).write_bytes(b'P6\n1 1\n255\n\xff\0\0' if field=='views' else b'raw video fixture, not decoded')
    atomic_json(folder/'contract.json',contract)
    atomic_json(folder/'dataset.json',{'purpose':'development_validation','samples':[sample],
        'ground_truth':{'labels':['action'],'samples':[{'sample_id':sample['sample_id'],'events':[event]}]}})
    llm={key:value for key,value in original['llm'].items() if key in ('model','base_url','provider','api_key_env','usage_ledger','usage_call_limit')}
    if not llm.get('usage_ledger'):llm.update(usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=1)
    llm['response_format']='json_object'
    before=snapshot(llm['usage_ledger']) if Path(llm['usage_ledger']).exists() else {'calls':0}
    config={'llm':llm,'remote':original['remote'],'research':{'max_planning_requests':1,
        'allow_candidate_writes':False,'allow_candidate_checks':True,'candidate_bundle_execution':{'media_input':True,'decode_video':False},
        'task_contract':{'path':str(folder/'contract.json'),'sha256':hashlib.sha256((folder/'contract.json').read_bytes()).hexdigest()},
        'validation_dataset':{'path':str(folder/'dataset.json'),'sha256':hashlib.sha256((folder/'dataset.json').read_bytes()).hexdigest()}}}
    atomic_json(folder/'preregistered.json',{'scope':__doc__,'max_planning_requests':1,'automatic_retries':0,
        'shared_usage_ledger_preserved':llm.get('usage_ledger')==original['llm'].get('usage_ledger'),
        'expected_tool':'evaluate_contract','expected_f1':1,'expected_remote_checks':1,'gpu_allowed':False})
    ledger=Ledger(folder)
    ledger.append('objective','objective',{'summary':'现有候选已准备好。请只选择 evaluate_contract，引用 prepared-candidate:result，按冻结媒体开发集计算事件 F1。不要修改代码或使用其他工具；结果只证明开发流程。'})
    observed=execute('inspect_repository',{},repo)
    ledger.append('inspect','action',{'summary':'实际源码检查','executor':'research-v1','tool':'inspect_repository'})
    ledger.append('inspect:result','result',{'summary':'已实际检查','action':'inspect','status':'completed','observation':observed})
    store=Candidates(folder/'candidates',repo)
    proposal={'hypothesis':'Verify end-to-end media execution','expected_improvement':'No model quality claim','evaluation_plan':'Fixed developer data',
        'edits':[{'path':'vision_rsi/adapter_planner_probe.py','base_sha256':None,
        'content':'import base64\ndef predict(sample,media):\n    raw=base64.b64decode(media["assets"][0]["content_base64"])\n    return {"events":[{"label":"action","start_seconds":0,"end_seconds":1}] if raw.startswith(b"P6") else []}\n'}]}
    candidate=store.create(proposal,{'fixture':True});store.close()
    ledger.append('prepared-candidate','action',{'summary':'实际生成隔离候选','executor':'research-v1','tool':'stage_candidate'})
    ledger.append('prepared-candidate:result','result',{'summary':'候选源码准备完毕，入口 vision_rsi.adapter_planner_probe.predict','action':'prepared-candidate',
        'status':'completed','observation':dict(candidate,source_edits=proposal['edits'])})
    calls=[];original_check=transport.check_candidate
    def counted(*values):calls.append(True);return original_check(*values)
    transport.check_candidate=counted;passed=False;failure=None
    try:
        research_step(config,folder,steps=1,repository=repo)
        result=ledger.events()[-1]['payload']
        assert result['status']=='completed' and result['observation']['metric_report']['event_micro_f1']==1
        action=next(e for e in ledger.events() if e['key']==result['action'])
        assert action['payload']['tool']=='evaluate_contract' and len(calls)==1
        assert len([e for e in ledger.events() if e['payload'].get('record_type')=='planning_request'])==1
        passed=True
    except Exception as error:failure=type(error).__name__+': '+str(error)[:500]
    finally:transport.check_candidate=original_check
    after=snapshot(llm['usage_ledger'])
    evidence={'passed':passed,'failure':failure,'remote_checks':len(calls),'usage_before':before,'usage_after':after,
        'gpu_used':False,'quality_verified':False,'capability_registered':False,'agent_adopted':False,'scope':__doc__}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2));return int(not passed)


if __name__=='__main__':raise SystemExit(main())
