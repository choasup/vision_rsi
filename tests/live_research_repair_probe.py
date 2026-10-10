"""One real repair planning call after an actual CPU sandbox failure."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.controller import execute,research_step
from vision_rsi.ledger import Ledger
from vision_rsi.llm_usage import snapshot
from vision_rsi.runner import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live:parser.error('--live required: one API admission, CPU SSH checks, no GPU')
    repo=Path(__file__).resolve().parents[1]
    local=json.loads(Path(args.config).read_text(encoding='utf-8'))
    name=local['llm'].get('api_key_env')
    if os.name=='nt' and name and not os.environ.get(name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            if isinstance(value,str):os.environ[name]=value
    folder=repo/'runs/research-repair-live'/uuid.uuid4().hex;folder.mkdir(parents=True)
    print(str(folder),flush=True)
    config={'llm':dict(local['llm'],usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=1,response_format='json_object'),
            'remote':local['remote'],'research':{'allow_candidate_writes':True,'allow_candidate_checks':True}}
    atomic_json(folder/'preregistered.json',{'api_call_limit':1,'gpu_allowed':False,'path':'vision_rsi/adapter_cpu_repair.py',
        'cases':[{'value':1},{'value':{'value':3}}],'expected':[{'value':2,'uid':65534},{'value':6,'uid':65534}],
        'criteria':['actual initial sandbox failure','one real model selects stage_candidate with repair',
                    'new immutable candidate passes fixed CPU cases'],'scope':'Public developer feedback fixture, not held-out RSI gain'})
    passed=False;failure=None
    try:
        observed=execute('inspect_repository',{},repo)
        ledger=Ledger(folder/'research')
        ledger.append('goal','objective',{'summary':'CPU开发修复验证：predict(value)必须支持整数1以及字典{"value":3}，均返回{"value":输入数值乘2,"uid":os.getuid()}。实际沙箱失败后只选择stage_candidate修复一个新候选，路径必须vision_rsi/adapter_cpu_repair.py，函数predict。新候选仍基于已检查的主仓库HEAD，该路径在主仓库不存在，base_sha256必须null；不要改目标或用例，不调用其它工具。不是训练或RSI效果实验。'})
        ledger.append('inspect','action',{'summary':'实际仓库检查','tool':'inspect_repository','executor':'research-v1'})
        ledger.append('inspect:result','result',{'summary':'实际仓库结果','action':'inspect','status':'completed','observation':observed})
        proposal={'hypothesis':'Deliberately incomplete developer fixture','expected_improvement':'None claimed',
            'evaluation_plan':'Fixed scalar and dict input cases','edits':[{'path':'vision_rsi/adapter_cpu_repair.py','base_sha256':None,
            'content':'import os\ndef predict(value):\n    return {"value": value * 2, "uid": os.getuid()}\n'}]}
        ledger.append('initial','action',{'summary':'故意不支持字典的开发候选','tool':'stage_candidate','executor':'research-v1',
            'refs':['inspect:result'],'arguments':{'base_revision':observed['git_revision'],'proposal':proposal}})
        with patch('vision_rsi.controller.OpenAICompatibleClient',side_effect=AssertionError('No planning during fixed setup')):
            research_step(config,ledger.directory,repository=repo)
        initial=ledger.events()[-1]['payload'];assert initial['status']=='completed'
        cases=[{'value':1},{'value':{'value':3}}]
        def check(key,candidate_id,ref):
            ledger.append(key,'action',{'summary':'固定CPU用例检查','tool':'check_candidate','executor':'research-v1','refs':[ref],
                'arguments':{'candidate_id':candidate_id,'module':'vision_rsi.adapter_cpu_repair','function':'predict','cases':cases}})
            with patch('vision_rsi.controller.OpenAICompatibleClient',side_effect=AssertionError('No planning during fixed check')):
                research_step(config,ledger.directory,repository=repo)
            result=ledger.events()[-1]['payload'];assert result['status']=='completed'
            return json.loads(Path(result['observation']['report_path']).read_text(encoding='utf-8'))
        first=check('initial-check',initial['observation']['candidate_id'],'initial:result')
        assert first['response']['status']=='failed' and 'TypeError' in first['response']['error']
        research_step(config,ledger.directory,repository=repo)
        repaired_event=ledger.events()[-1];repaired=repaired_event['payload']
        assert repaired_event['kind']=='result' and repaired['status']=='completed'
        new_id=repaired['observation']['candidate_id'];assert new_id!=initial['observation']['candidate_id']
        last=check('repaired-check',new_id,repaired_event['key'])
        assert last['response']['status']=='executed_unverified'
        assert last['response']['observation']['results']==[{'value':2,'uid':65534},{'value':6,'uid':65534}]
        passed=True
    except Exception as error:
        failure=type(error).__name__+': '+str(error)[:1000]
    usage=snapshot(str(folder/'usage.sqlite3')) if (folder/'usage.sqlite3').exists() else None
    passed=passed and usage is not None and usage['calls']==1
    result={'directory':str(folder),'passed':passed,'failure':failure,'usage':usage,'gpu_used':False,'adopted':False,
            'scope':'Actual CPU failure and one model repair on fixed public developer cases; no RSI gain proof'}
    atomic_json(folder/'evidence.json',result);print(json.dumps(result,indent=2))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
