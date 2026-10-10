"""Task-bound candidate trials on new inputs, without capability promotion."""
import base64
import hashlib
import json
from pathlib import Path
import re

from .campaign import lease
from .candidate_bundle import run
from .candidate_runtime import encode_cases
from .candidate_serving import _checked, check
from .contracts import validate_sample
from .event_eval import read_document
from .input_provenance import manifest
from .runner import atomic_json, digest
from .task_acceptance import pending_candidate


def infer(registry, session, version, request_id, samples, media_directory, remote):
    if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',request_id):
        raise ValueError('Require a stable safe request ID of 1..64 characters')
    name,artifact,task_binding,bundle=pending_candidate(registry,session,version)
    report=_checked(registry.root/name/'candidate-serving/serving.json')
    _,serving_binding=read_document(registry.root/name/'candidate-serving/binding.json',4*1024*1024)
    serving=check(registry,session,version,report['acceptance_dataset_path'],remote,
                  serving_binding['max_latency_seconds'],cached_only=True)
    if serving['status']!='serving_contract_checks_met' or not serving.get('userspace_snapshot_verified'):
        raise ValueError('Require met serving checks with frozen userspace identity')
    runtime=_checked(registry.root/name/'candidate-serving/trial-0.json')
    from .input_provenance import _read
    baseline,_=_read(runtime['execution_path'])
    runtime_hash=baseline['runtime_identity_sha256']
    contract=json.loads(base64.b64decode(bundle['contract_base64']))
    if not isinstance(samples,list) or not 1<=len(samples)<=16:raise ValueError('Require 1..16 samples')
    cases=[]
    for sample in samples:
        validate_sample(contract,sample)
        case={'sample':sample}
        if bundle['identity'].get('media_transport')=='vision_sample_transport_v1':
            from .media import package_sample
            case['media']=package_sample(contract,sample,media_directory,content_limit=512*1024)
        cases.append(case)
    if len({sample['sample_id'] for sample in samples})!=len(samples):raise ValueError('Duplicate sample IDs in batch')
    encode_cases(bundle['identity']['module'],bundle['identity']['function'],cases)
    rows=manifest(contract,cases)
    binding={'task_binding':task_binding,'version':version,'request_id':request_id,'samples':samples,
             'input_manifest':rows,'remote':remote,'runtime_identity_sha256':runtime_hash,
             'serving_record_sha256':serving['record_sha256'],
             'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    root=registry.root/name/'candidate-inference'/request_id
    root.mkdir(parents=True,exist_ok=True)
    with lease(root/'request.lock',owner='Candidate inference request'):
        path=root/'binding.json'
        if path.exists():
            _,saved=read_document(path,4*1024*1024)
            if saved!=binding:raise ValueError('Request ID already bound to different inputs or evidence')
        else:atomic_json(path,binding)
        execution=run(artifact/'bundle.json',samples,remote,root/'execution',bundle['bundle_id'],
                      media_directory,rows,expected_runtime_identity_sha256=runtime_hash)
        result={'task_id':name,'version':version,'request_id':request_id,'status':'candidate_trial_completed',
                'sample_ids':[sample['sample_id'] for sample in samples],'outputs':execution['outputs'],
                'execution_path':execution['execution_path'],'execution_record_sha256':execution['record_sha256'],
                'binding_sha256':digest(binding),'quality_verified':False,'production_accepted':False,
                'scope':'New-input candidate trial; frozen holdout/serving checks do not guarantee quality on these inputs.'}
        result['record_sha256']=digest(result)
        output=root/'result.json'
        if output.exists() and _checked(output)!=result:raise ValueError('Saved candidate inference result differs')
        if not output.exists():atomic_json(output,result)
        return result
