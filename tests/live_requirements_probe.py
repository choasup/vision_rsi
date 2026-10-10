"""Explicit live development probe; never run by unittest discovery or train models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.contracts import Sessions,issues,GPU_BUDGET_QUESTION
from vision_rsi.llm_usage import snapshot
from vision_rsi.runner import atomic_json
from vision_rsi.video_runtime import compile_plan

CASES=[
 {'id':'single-missing-budget','goal':'我要一个COCO80类别单图检测任务。每个推理样本只有一张图片，不需要文本，不要把训练标注作为推理输入。输出detections，里面每项有category_id、bbox、score。在COCO2017 val标准box AP至少60（0到100量纲）。训练GPU小时预算还没决定，其它实现细节你自行选，不要再问我JSON或优化器怎么写。',
  'expected':{'kind':'image','threshold':60,'budget':None,'question':GPU_BUDGET_QUESTION}},
 {'id':'joint-inspection','goal':'同一工件每次输入2到5张不同视角图片，这些图必须联合判断，不是批量独立图片。缺陷类别只有scratch和dent。输出defects数组，每项包含label，值为scratch或dent，以及severity，值为low或high。在独立标注保留集上按每个工件和类别统计micro_F1，至少0.85，越高越好。GPU训练预算12小时。其它实现细节由你决定。',
  'expected':{'kind':'image_list','threshold':.85,'budget':12,'min_items':2,'max_items':5,'output':'defects','labels':['scratch','dent']}},
 {'id':'video-events','goal':'输入一个视频clip，每秒采样3帧，保留原始时间戳和帧顺序，忽略音频。输出events数组，每项包含label（只允许fallen或standing）、start_seconds和end_seconds。用独立标注保留集做事件F1，类别一致并且时间IoU至少0.5才算匹配，F1至少0.9，越高越好。GPU训练预算10小时。模型和实现你自己选。',
  'expected':{'kind':'video','threshold':.9,'budget':10,'output':'events','labels':['fallen','standing']}}
]


def check_contract(contract,expected):
    checks={}
    fields=contract.get('inputs',{})
    checks['one_inference_input']=isinstance(fields,dict) and len(fields)==1
    field=next(iter(fields.values()),{}) if isinstance(fields,dict) else {}
    checks['input_kind']=field.get('type')==expected['kind'] and field.get('required') is True
    acceptance=contract.get('acceptance') or {}
    checks['threshold']=acceptance.get('threshold')==expected['threshold']
    checks['maximize']=acceptance.get('direction')=='maximize'
    budget=contract.get('budget')
    if expected['budget'] is None:
        checks['budget_not_invented']=budget is None or budget=={}
        checks['only_missing_budget_question']=contract.get('open_questions')==[expected['question']]
        checks['task_defined_without_schema_questions']=all('预算' in issue or issue.startswith('待澄清:') for issue in issues(contract))
    else:
        checks['budget']=isinstance(budget,dict) and budget=={'gpu_hours':expected['budget']}
        checks['fully_defined_interface']=not issues(contract)
    if expected['kind']=='image_list':
        checks['joint_bounds']=field.get('semantics')=='joint' and all(field.get(key)==expected[key] for key in ('min_items','max_items'))
    if expected['kind']=='video':
        policy=field.get('processing') or {}
        compiled=compile_plan(policy)
        checks['video_sampling']=compiled['status']=='ready' and compiled['plan']['fps']==3
        checks['video_audio']=policy.get('audio')=='ignore'
        temporal=policy.get('temporal','').lower()
        checks['video_time_order']=('timestamp' in temporal or '时间戳' in temporal) and ('order' in temporal or '顺序' in temporal)
    if 'output' in expected:
        schema=contract.get('output_schema') or {};output=(schema.get('properties') or {}).get(expected['output'],{})
        checks['output_array']=output.get('type')=='array' and expected['output'] in schema.get('required',[])
        properties=(output.get('items') or {}).get('properties') or {}
        checks['label_enum']=set((properties.get('label') or {}).get('enum',[]))==set(expected['labels'])
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--config',default='config.local.json');parser.add_argument('--root',default='runs/requirements-live');args=parser.parse_args()
    if not args.live:parser.error('Explicit --live required: up to six actual API admissions, no training')
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))['llm']
    name=config.get('api_key_env')
    if os.name=='nt' and isinstance(name,str) and not os.environ.get(name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            if isinstance(value,str):os.environ[name]=value
    folder=Path(args.root).resolve()/uuid.uuid4().hex;folder.mkdir(parents=True)
    llm=dict(config,usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=6)
    manifest={'scorer_version':2,'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':CASES,'model':config.get('model'),'max_api_admissions':6,'scope':'Fixed independent development cases; not hidden benchmark, not model quality or research efficiency.',
              'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].joinpath('vision_rsi').glob('*.py')}}
    atomic_json(folder/'preregistered.json',manifest)
    store=Sessions(folder/'sessions');results=[]
    for case in CASES:
        session=store.create('probe-'+case['id'],case['goal'])['session_id']
        try:
            result=store.clarify(session,llm)
            contract=result['versions'][-1]['contract']
            checks=check_contract(contract,case['expected'])
            record={'case_id':case['id'],'session_id':session,'status':result['status'],'checks':checks,'passed':all(checks.values()),'contract':contract,'issues':result['versions'][-1]['issues']}
        except Exception as error:
            record={'case_id':case['id'],'session_id':session,'passed':False,'error_type':type(error).__name__,'scope':'Failure retained; no automatic semantic retry.'}
        results.append(record);atomic_json(folder/(case['id']+'.json'),record)
        print(json.dumps({key:value for key,value in record.items() if key not in ('contract','issues')},ensure_ascii=False),flush=True)
    usage=snapshot(str(folder/'usage.sqlite3')) if (folder/'usage.sqlite3').exists() else None
    summary={'directory':str(folder),'passed':all(row['passed'] for row in results),'cases':len(results),'passed_cases':sum(row['passed'] for row in results),'usage':usage,'training_performed':False,'semantic_tuning_or_retry':False,'preregistration_sha256':hashlib.sha256((folder/'preregistered.json').read_bytes()).hexdigest()}
    atomic_json(folder/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
    raise SystemExit(not summary['passed'])


if __name__=='__main__':main()
