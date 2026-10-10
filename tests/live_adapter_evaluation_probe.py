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
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; two bounded CPU sandbox checks, no GPU/API')
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
    atomic_json(folder/'preregistered.json',{'scope':__doc__,'llm_calls':0,'gpu_allowed':False,'expected_remote_checks':2,
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
