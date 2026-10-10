"""One real planner call selecting a hash-bound read-only source action."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
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
    if not args.live:parser.error('--live required; one admitted API call, no remote/GPU')
    repo=Path(__file__).resolve().parents[1]
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    name=config['llm'].get('api_key_env')
    if os.name=='nt' and isinstance(name,str) and not os.environ.get(name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            if isinstance(value,str):os.environ[name]=value
    folder=repo/'runs/source-research-live'/uuid.uuid4().hex;folder.mkdir(parents=True)
    config={'llm':dict(config['llm'],usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=1),'remote':{}}
    target='vision_rsi/controller.py'
    observation=execute('inspect_repository',{},repo)
    checksum=observation['source_sha256'][target]
    atomic_json(folder/'preregistered.json',{'target':target,'start_line':31,'max_lines':20,
        'expected_source_sha256':checksum,'actual_api_call_limit':1,'remote_allowed':False,'gpu_allowed':False,
        'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'criteria':['planner selects read_source for requested line range','tool result matches actual source bytes and hash',
                    'exactly one API admission','no semantic retries']})
    ledger=Ledger(folder/'research')
    ledger.append('goal','objective',{'summary':'请根据仓库检查证据，细读 vision_rsi/controller.py 的第31行起20行。只选择 read_source，使用检查记录中该文件的SHA256，不重复仓库检查，不调用远端，不做synthesize。此为工具链开发验证，不是模型质量评测。'})
    ledger.append('inspect','action',{'summary':'实际本地仓库检查','tool':'inspect_repository','executor':'research-v1','refs':['goal']})
    ledger.append('inspect:result','result',{'summary':'实际源码文件哈希与有界片段','action':'inspect',
        'status':'completed','observation':observation,'read_only':True,'synthetic':False})
    failure=None;passed=False
    try:
        research_step(config,folder/'research',steps=1,repository=repo)
        events=ledger.events()
        result=events[-1]
        action=next(e for e in events if e['key']==result['payload'].get('action'))
        assert action['payload']['tool']=='read_source'
        assert action['payload']['arguments']=={'path':target,'start_line':31,'max_lines':20,'expected_sha256':checksum}
        observed=result['payload']['observation']
        raw=(repo/target).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==checksum
        assert observed['source_excerpt']==''.join(raw.decode('utf-8-sig').splitlines(keepends=True)[30:50])
        assert result['payload']['status']=='completed' and observed['source_sha256']==checksum
        passed=True
    except Exception as error:
        failure=type(error).__name__
    usage=snapshot(str(folder/'usage.sqlite3')) if (folder/'usage.sqlite3').exists() else None
    passed=passed and usage is not None and usage['calls']==1
    evidence={'directory':str(folder),'passed':passed,'failure_type':failure,'usage':usage,
              'source_sha256':checksum,'remote_called':False,'gpu_used':False,'training_performed':False,
              'semantic_retries':0,'scope':'One requested source range, real API and local read-only tool; no autonomous research-quality or RSI gain proof.'}
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps(evidence,indent=2))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
