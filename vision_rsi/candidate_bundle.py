"""Portable, content-addressed source artifacts; never production approval."""
import base64
import hashlib
from pathlib import Path
import re
import json
from .runner import digest
from .event_eval import read_document
from .candidate_runtime import encode_cases
from .contracts import validate_schema_definition


def verify(path):
    _,bundle=read_document(path,8*1024*1024)
    if not isinstance(bundle,dict) or set(bundle)!={'bundle_id','identity','files','contract_base64'}:raise ValueError('Invalid candidate bundle')
    identity=bundle['identity']
    if digest(identity)!=bundle['bundle_id'] or identity.get('format')!='vision-rsi/development-candidate/v1':raise ValueError('Bundle identity mismatch')
    if identity.get('production_accepted') is not False:raise ValueError('Development bundle cannot approve production')
    if identity.get('media_transport','json_only') not in ('json_only','vision_sample_transport_v1'):raise ValueError('Unsupported bundle media transport')
    encode_cases(identity['module'],identity['function'],[{'sample':{}}])
    if set(bundle['files'])!=set(identity['source_hashes']):raise ValueError('Bundle source set mismatch')
    for name,content in bundle['files'].items():
        if not re.fullmatch(r'vision_rsi/[A-Za-z_][A-Za-z0-9_]*\.py',name):raise ValueError('Invalid bundle source path')
        raw=base64.b64decode(content,validate=True)
        if hashlib.sha256(raw).hexdigest()!=identity['source_hashes'][name]:raise ValueError('Bundle source hash mismatch')
    contract=base64.b64decode(bundle['contract_base64'],validate=True)
    if hashlib.sha256(contract).hexdigest()!=identity['contract_sha256']:raise ValueError('Bundle contract hash mismatch')
    return bundle


def build(store,candidate_id,module,function,contract_path,output,media_input=False):
    encode_cases(module,function,[{'sample':{}}])
    raw,contract=read_document(contract_path,512*1024)
    if not isinstance(contract,dict) or not isinstance(contract.get('inputs'),dict) or not contract['inputs']:raise ValueError('Bundle requires a task interface')
    validate_schema_definition(contract.get('output_schema'))
    record,files=store.source_files(candidate_id)
    if module.replace('.','/')+'.py' not in files:raise ValueError('Entry module is absent from candidate sources')
    if sum(map(len,files.values()))>2*1024*1024:raise ValueError('Candidate source bundle exceeds byte limit')
    identity={'format':'vision-rsi/development-candidate/v1','candidate_id':candidate_id,'git_revision':record['git_revision'],
              'module':module,'function':function,'contract_sha256':hashlib.sha256(raw).hexdigest(),
              'source_hashes':{name:hashlib.sha256(content).hexdigest() for name,content in files.items()},'production_accepted':False}
    if media_input:identity['media_transport']='vision_sample_transport_v1'
    bundle={'bundle_id':digest(identity),'identity':identity,'files':{name:base64.b64encode(content).decode('ascii') for name,content in files.items()},
            'contract_base64':base64.b64encode(raw).decode('ascii')}
    folder=Path(output).resolve()/bundle['bundle_id'];folder.mkdir(parents=True,exist_ok=True);path=folder/'bundle.json'
    if path.exists():
        if verify(path)!=bundle:raise ValueError('Existing bundle differs; refusing overwrite')
    else:
        with path.open('x',encoding='utf-8') as stream:json.dump(bundle,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
        verify(path)
    return {'bundle_id':bundle['bundle_id'],'directory':str(folder),'path':str(path),'production_accepted':False,'capability_registered':False}


def run(bundle_path,samples,remote,output,expected_bundle_id=None,media_directory=None):
    from .contracts import validate_sample,validate_schema
    from .campaign import lease
    from .runner import atomic_json
    from .remote import check_candidate
    bundle=verify(bundle_path);identity=bundle['identity']
    if expected_bundle_id is not None and bundle['bundle_id']!=expected_bundle_id:raise ValueError('Pinned bundle identity changed')
    contract=json.loads(base64.b64decode(bundle['contract_base64']).decode('utf-8-sig'))
    if not isinstance(samples,list) or not 1<=len(samples)<=16:raise ValueError('Require 1..16 samples')
    for sample in samples:validate_sample(contract,sample)
    cases=[{'sample':sample} for sample in samples]
    if identity.get('media_transport')=='vision_sample_transport_v1':
        from .media import package_sample
        if media_directory is None:raise ValueError('Media bundle needs an explicit input base directory')
        cases=[]
        for sample in samples:
            cases.append({'sample':sample,'media':package_sample(contract,sample,media_directory,content_limit=512*1024)})
            encode_cases(identity['module'],identity['function'],cases)
    encode_cases(identity['module'],identity['function'],cases)
    request={'files':bundle['files'],'source_hashes':identity['source_hashes'],
             'module':identity['module'],'function':identity['function'],'cases':cases}
    binding={'bundle_id':bundle['bundle_id'],'request_sha256':digest(request),'remote':remote,
             'executor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'validator_sha256':hashlib.sha256(Path(__file__).with_name('contracts.py').read_bytes()).hexdigest()}
    folder=Path(output).resolve()/digest(binding);folder.mkdir(parents=True,exist_ok=True);path=folder/'execution.json'
    with lease(folder/'execution.lock',owner='Candidate bundle execution'):
        if path.exists():
            _,saved=read_document(path,8*1024*1024)
            if saved.get('binding')!=binding:raise ValueError('Saved bundle execution binding changed')
            if saved['status']=='reserved':raise RuntimeError('Uncertain bundle execution; not repeated automatically')
            if saved.get('record_sha256')!=digest({key:value for key,value in saved.items() if key!='record_sha256'}):raise ValueError('Saved bundle execution content changed')
            if saved['status']!='development_execution_completed' or saved.get('production_accepted') is not False:raise ValueError('Invalid development execution state')
            for result in saved['outputs']:validate_schema(contract['output_schema'],result)
            return saved
        record={'binding':binding,'status':'reserved','production_accepted':False,'capability_registered':False,
                'quality_verified':False,'gpu_used':False}
        atomic_json(path,record)
        response=check_candidate(remote,request)
        if response.get('source_hashes')!=identity['source_hashes']:raise ValueError('Runtime source identity mismatch')
        limits=response.get('limits',{})
        if limits.get('gpu') is not False or limits.get('network') is not False:raise ValueError('Runtime isolation evidence missing')
        results=response.get('observation',{}).get('results')
        if response.get('status')!='executed_unverified' or not isinstance(results,list) or len(results)!=len(samples):
            raise ValueError('Bundle runtime did not produce one output per input')
        for result in results:validate_schema(contract['output_schema'],result)
        record.update(status='development_execution_completed',outputs=results,limits=limits,
                      response_sha256=digest(response),execution_path=str(path))
        record['record_sha256']=digest(record)
        atomic_json(path,record);return record


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(prog='vision-rsi candidate-run',description='Execute a development bundle in CPU sandbox; no production acceptance')
    parser.add_argument('--bundle',required=True);parser.add_argument('--bundle-id')
    parser.add_argument('--input',required=True,help='Single sample object or list of 1..16 samples')
    parser.add_argument('--output',default='runs/candidate-executions');parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args(argv)
    try:
        _,samples=read_document(args.input,512*1024)
        if isinstance(samples,dict):samples=[samples]
        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        print(json.dumps(run(args.bundle,samples,config['remote'],args.output,args.bundle_id,Path(args.input).resolve().parent),ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:parser.exit(1,str(error)+'\n')
