"""Real CPU sandbox metric plumbing on fixed fixtures; no vision-quality claim."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.adapter_evaluation import evaluate
from vision_rsi.candidates import Candidates
from vision_rsi.event_eval import PROTOCOL
from vision_rsi.runner import atomic_json
import vision_rsi.remote as transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true');parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--lineage',action='store_true',help='Also verify inherited-module execution in a child candidate')
    parser.add_argument('--bundle-execution',action='store_true',help='Also execute an independent copy of the child bundle')
    parser.add_argument('--media-bundle',action='store_true',help='Verify raw local media bytes reach isolated candidate code')
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; two bounded CPU sandbox checks, no GPU/API')
    if args.bundle_execution and not args.lineage:parser.error('--bundle-execution requires --lineage')
    if args.media_bundle and not args.bundle_execution:parser.error('--media-bundle requires --bundle-execution')
    repo=Path(__file__).resolve().parents[1]
    remote=json.loads(Path(args.config).read_text(encoding='utf-8'))['remote']
    folder=repo/'runs/adapter-evaluation-live'/uuid.uuid4().hex;folder.mkdir(parents=True)
    print(str(folder),flush=True)
    contract=json.loads((repo/'examples/interface-contract.json').read_text(encoding='utf-8'))
    contract['goal']='Developer event metric fixture; no image or video content is read'
    contract['acceptance']={'metric':'event_micro_f1','direction':'maximize','evaluation_protocol':PROTOCOL,
                            'iou_threshold':0.5,'threshold':0.95}
    contract['output_schema']={'type':'object','properties':{'events':{'type':'array','items':{'type':'object',
        'properties':{'label':{'type':'string','enum':['action']},'start_seconds':{'type':'number','minimum':0},
                      'end_seconds':{'type':'number','minimum':0}},'required':['label','start_seconds','end_seconds'],
        'additionalProperties':False}}},'required':['events'],'additionalProperties':False}
    event={'label':'action','start_seconds':0,'end_seconds':1}
    contract['example_output']={'events':[event]}
    atomic_json(folder/'contract.json',contract)
    datasets=[]
    for name,start in (('matching',0),('different',2)):
        document={'purpose':'development_validation','samples':[dict(contract['example_input'],sample_id='fixture')],
                  'ground_truth':{'labels':['action'],'samples':[{'sample_id':'fixture',
                       'events':[dict(event,start_seconds=start,end_seconds=start+1)]}]}}
        path=folder/(name+'.json');atomic_json(path,document);datasets.append(path)
    proposal={'hypothesis':'Verify isolated execution to deterministic metric linkage',
              'expected_improvement':'No visual-model or research-efficiency improvement claimed',
              'evaluation_plan':'Fixed matching/nonmatching event fixtures; repeated context must reuse runtime evidence',
              'edits':[{'path':'vision_rsi/adapter_metric_probe.py','base_sha256':None,
                        'content':'import os\ndef predict(sample):\n    events = [{"label":"action", "start_seconds":0, "end_seconds":1}] if os.getuid() == 65534 else []\n    return {"events":events}\n'}]}
    atomic_json(folder/'preregistered.json',{'scope':__doc__,'llm_calls':0,'gpu_allowed':False,'expected_remote_checks':5 if args.media_bundle else (4 if args.bundle_execution else (3 if args.lineage else 2)),
        'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'expected_f1':[1,0],'criteria':['actual UID65534-dependent adapter output','matching metric met','different metric not met',
        'exact duplicate reuses saved runtime','network and GPU disabled','no capability registration or agent adoption']})
    calls=[];original=transport.check_candidate
    def counted(endpoint,request):
        calls.append(request['source_hashes'])
        return original(endpoint,request)
    store=None;passed=False;failure=None;reports=[]
    transport.check_candidate=counted
    try:
        store=Candidates(folder/'candidates',repo)
        candidate=store.create(proposal,{'fixture':True,'scope':'CPU metric developer probe'})['candidate_id']
        for dataset in datasets:
            reports.append(evaluate(store,candidate,remote,'vision_rsi.adapter_metric_probe','predict',folder/'contract.json',dataset))
        assert [report['metric_report']['event_micro_f1'] for report in reports]==[1,0]
        assert [report['status'] for report in reports]==['development_metric_met','development_metric_not_met']
        for report in reports:
            execution=json.loads(Path(report['adapter_report_path']).read_text(encoding='utf-8'))['response']
            assert execution['limits']['gpu'] is False and execution['limits']['network'] is False
            assert not report['quality_verified'] and not report['capability_registered'] and not report['agent_adopted']
        repeated=evaluate(store,candidate,remote,'vision_rsi.adapter_metric_probe','predict',folder/'contract.json',datasets[0])
        assert repeated==reports[0] and len(calls)==2
        if args.lineage:
            parent=json.loads((store.root/candidate/'candidate.json').read_text(encoding='utf-8'))
            child_store=Candidates(store.root,parent['checkout'])
            try:
                child=child_store.create(dict(proposal,edits=[{'path':'vision_rsi/harness_metric_child.py','base_sha256':None,
                    'content':'from vision_rsi.adapter_metric_probe import predict\n'}]),
                    {'fixture':True,'lineage_mode':'git_parent','parent_candidate_id':candidate},base=parent['git_revision'])
            finally:child_store.close()
            child_report=evaluate(store,child['candidate_id'],remote,'vision_rsi.harness_metric_child','predict',folder/'contract.json',datasets[0])
            reports.append(child_report)
            assert child_report['metric_report']['event_micro_f1']==1
            assert 'vision_rsi/adapter_metric_probe.py' in calls[-1] and 'vision_rsi/harness_metric_child.py' in calls[-1]
            repeated=evaluate(store,child['candidate_id'],remote,'vision_rsi.harness_metric_child','predict',folder/'contract.json',datasets[0])
            assert repeated==child_report and len(calls)==3
            if args.bundle_execution:
                from vision_rsi.candidate_bundle import build,run
                bundle=build(store,child['candidate_id'],'vision_rsi.harness_metric_child','predict',folder/'contract.json',folder/'bundles')
                portable=folder/'independent-bundle.json';portable.write_bytes(Path(bundle['path']).read_bytes())
                sample=json.loads(datasets[0].read_text(encoding='utf-8'))['samples']
                execution=run(portable,sample,remote,folder/'bundle-executions',bundle['bundle_id'])
                assert execution['outputs']==[{'events':[event]}]
                assert run(portable,sample,remote,folder/'bundle-executions',bundle['bundle_id'])==execution
                assert len(calls)==4 and not execution['quality_verified']
                if args.media_bundle:
                    media_source='import base64\ndef predict(sample, media):\n    raw=base64.b64decode(media["assets"][0]["content_base64"])\n    ok=raw==b"P6\\n1 1\\n255\\n\\xff\\x00\\x00" and len(media["assets"])==3\n    return {"events":[{"label":"action","start_seconds":0,"end_seconds":1}] if ok else []}\n'
                    media_proposal=dict(proposal,edits=[{'path':'vision_rsi/adapter_media_probe.py','base_sha256':None,'content':media_source}])
                    media_candidate=store.create(media_proposal,{'fixture':True,'scope':'raw media transport only'})
                    media_bundle=build(store,media_candidate['candidate_id'],'vision_rsi.adapter_media_probe','predict',folder/'contract.json',folder/'bundles',media_input=True)
                    media_sample=json.loads(json.dumps(sample[0]))
                    for field,value in media_sample['inputs'].items():
                        items=value['items'] if value['type']=='image_list' else [value]
                        for index,item in enumerate(items):
                            name=field+str(index)+'.bin';item['uri']=name
                            (folder/name).write_bytes(b'P6\n1 1\n255\n\xff\x00\x00' if field=='views' else b'raw video transport fixture, not decoded')
                    actual=run(media_bundle['path'],[media_sample],remote,folder/'media-executions',media_directory=folder)
                    assert actual['outputs']==[{'events':[event]}] and len(calls)==5
                    assert run(media_bundle['path'],[media_sample],remote,folder/'media-executions',media_directory=folder)==actual
                    assert len(calls)==5
        passed=True
    except Exception as error:failure=type(error).__name__+': '+str(error)[:500]
    finally:
        transport.check_candidate=original
        if store is not None:store.close()
    result={'directory':str(folder),'passed':passed,'failure':failure,'remote_checks':len(calls),'llm_called':False,
            'gpu_used':False,'quality_verified':False,'capability_registered':False,'agent_adopted':False,
            'report_paths':[report['report_path'] for report in reports],'scope':__doc__}
    atomic_json(folder/'evidence.json',result);print(json.dumps(result,indent=2));return int(not passed)


if __name__=='__main__':raise SystemExit(main())
