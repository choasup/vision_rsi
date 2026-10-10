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
    encode_cases(identity['module'],identity['function'],[{'sample':{}}])
    if set(bundle['files'])!=set(identity['source_hashes']):raise ValueError('Bundle source set mismatch')
    for name,content in bundle['files'].items():
        if not re.fullmatch(r'vision_rsi/[A-Za-z_][A-Za-z0-9_]*\.py',name):raise ValueError('Invalid bundle source path')
        raw=base64.b64decode(content,validate=True)
        if hashlib.sha256(raw).hexdigest()!=identity['source_hashes'][name]:raise ValueError('Bundle source hash mismatch')
    contract=base64.b64decode(bundle['contract_base64'],validate=True)
    if hashlib.sha256(contract).hexdigest()!=identity['contract_sha256']:raise ValueError('Bundle contract hash mismatch')
    return bundle


def build(store,candidate_id,module,function,contract_path,output):
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
    bundle={'bundle_id':digest(identity),'identity':identity,'files':{name:base64.b64encode(content).decode('ascii') for name,content in files.items()},
            'contract_base64':base64.b64encode(raw).decode('ascii')}
    folder=Path(output).resolve()/bundle['bundle_id'];folder.mkdir(parents=True,exist_ok=True);path=folder/'bundle.json'
    if path.exists():
        if verify(path)!=bundle:raise ValueError('Existing bundle differs; refusing overwrite')
    else:
        with path.open('x',encoding='utf-8') as stream:json.dump(bundle,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
        verify(path)
    return {'bundle_id':bundle['bundle_id'],'directory':str(folder),'path':str(path),'production_accepted':False,'capability_registered':False}
