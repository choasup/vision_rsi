"""Explicit remote CPU check through the research controller; no LLM or GPU."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.controller import execute,research_step
from vision_rsi.ledger import Ledger
from vision_rsi.runner import atomic_json,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true')
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--contract',action='store_true',help='Verify frozen interface conformance using fixed outputs, not media inference')
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required')
    repo=Path(__file__).resolve().parents[1]
    local=json.loads(Path(args.config).read_text(encoding='utf-8'))
    config={'llm':{},'remote':local['remote'],'research':{'allow_candidate_writes':True,'allow_candidate_checks':True}}
    folder=repo/'runs/research-candidate-live'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    print(str(folder),flush=True)
    contract=None
    if args.contract:
        path=repo/'examples/interface-contract.json'
        raw=path.read_bytes();contract=json.loads(raw)
        config['research']['task_contract']={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    atomic_json(folder/'preregistered.json',{'scope':'Fixed CPU developer fixture, not model quality or autonomous proposal selection',
        'mode':'contract' if args.contract else 'scalar',
        'frozen_contract':config['research'].get('task_contract'),
        'llm_calls':0,'gpu_allowed':False,'expected_values':None if args.contract else [2,6],
        'expected_uid':None if args.contract else 65534,
        'criteria':['controller stages isolated Git candidate','controller receives actual CPU sandbox output',
                    'same check under another action binding reuses saved report without transport']+
                   (['valid interface output passes','negative output time fails interface validation'] if args.contract else [])})
    passed=False;failure=None
    try:
        observation=execute('inspect_repository',{},repo)
        ledger=Ledger(folder/'research')
        ledger.append('goal','objective',{'summary':'固定CPU开发探针：验证独立候选创建、沙箱返回与收据恢复；不研究模型效果。'})
        ledger.append('inspect','action',{'summary':'实际仓库检查','tool':'inspect_repository','executor':'research-v1'})
        ledger.append('inspect:result','result',{'summary':'实际观察','action':'inspect','status':'completed','observation':observation})
        proposal={'hypothesis':'CPU fixture verifies the research execution transport',
            'expected_improvement':'No research-efficiency improvement claimed','evaluation_plan':'Exact doubling and sandbox UID; no quality claim',
            'edits':[{'path':'vision_rsi/adapter_cpu_probe.py','base_sha256':None,
                      'content':'import os\ndef predict(value):\n    return {"value": value * 2, "uid": os.getuid()}\n'}]}
        if args.contract:
            proposal['edits'][0]['content']='def predict(sample):\n    time = -1 if sample["sample_id"].endswith("invalid") else 1.2\n    return {"defects": [{"label": "scratch", "start_seconds": time}]}\n'
        ledger.append('stage','action',{'summary':'固定开发用例候选','tool':'stage_candidate','executor':'research-v1','refs':['inspect:result'],
            'arguments':{'base_revision':observation['git_revision'],'proposal':proposal}})
        with patch('vision_rsi.controller.OpenAICompatibleClient',side_effect=AssertionError('No API allowed')):
            research_step(config,ledger.directory,repository=repo)
        stage=ledger.events()[-1]['payload']
        assert stage['status']=='completed'
        candidate_id=stage['observation']['candidate_id']
        check={'candidate_id':candidate_id,'module':'vision_rsi.adapter_cpu_probe','function':'predict','cases':[{'value':1},{'value':3}]}
        tool='check_contract' if args.contract else 'check_candidate'
        if args.contract:
            check.pop('cases');check['samples']=[contract['example_input']]
        ledger.append('check','action',{'summary':'实际远端CPU沙箱','tool':tool,'executor':'research-v1',
            'refs':['stage:result'],'arguments':check})
        with patch('vision_rsi.controller.OpenAICompatibleClient',side_effect=AssertionError('No API allowed')):
            research_step(config,ledger.directory,repository=repo)
        checked=ledger.events()[-1]['payload']
        assert checked['status']=='completed'
        report=json.loads(Path(checked['observation']['report_path']).read_text(encoding='utf-8'))
        response=report['response']
        assert response['status']=='executed_unverified'
        if args.contract:
            assert report['status']=='adapter_contract_passed'
            assert response['observation']['results']==[contract['example_output']]
        else:
            assert response['observation']['results']==[{'value':2,'uid':65534},{'value':6,'uid':65534}]
        assert response['limits']['gpu'] is False and response['limits']['network'] is False
        context={'store':str(ledger.directory/'candidates'),
                 'binding':{'action_key':'another-action','objective_sha256':digest(ledger.events()[0]['payload'])}}
        with patch('vision_rsi.remote.check_candidate',side_effect=AssertionError('Recovery must not send transport')):
            recovered=execute(tool,dict(config,_research_candidate_context=context),repo,check)
        assert recovered['report_sha256']==checked['observation']['report_sha256']
        atomic_json(folder/'controller-result.json',checked)
        if args.contract:
            invalid=json.loads(json.dumps(contract['example_input']));invalid['sample_id']='development-invalid'
            bad=dict(check,samples=[invalid])
            ledger.append('invalid-check','action',{'summary':'固定无效输出用例','tool':tool,'executor':'research-v1',
                'refs':['stage:result'],'arguments':bad})
            with patch('vision_rsi.controller.OpenAICompatibleClient',side_effect=AssertionError('No API allowed')):
                research_step(config,ledger.directory,repository=repo)
            failure_result=ledger.events()[-1]['payload']
            assert failure_result['status']=='completed'
            assert failure_result['observation']['runtime_status']=='adapter_contract_failed'
            assert failure_result['observation']['contract_failures']
            atomic_json(folder/'rejected-output.json',failure_result)
        passed=True
    except Exception as error:
        failure=type(error).__name__+': '+str(error)[:1000]
    evidence={'directory':str(folder),'passed':passed,'failure':failure,'llm_called':False,'gpu_used':False,
              'mode':'contract' if args.contract else 'scalar',
              'remote_allowed':True,'quality_verified':False,'adopted':False,
              'scope':'Fixed developer fixture; no autonomous planning or RSI gain proof'}
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps(evidence,indent=2))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
