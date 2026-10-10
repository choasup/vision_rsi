"""Immutable task delivery, scoped to a sealed research ledger and holdout."""
import base64
import hashlib
import json
from pathlib import Path

from .runner import atomic_json,digest
from .capability import sha,task_id
from .candidate_serving import _checked,check
from .event_eval import read_document
from .task_acceptance import pending_candidate,status


def review(registry,session,version,research_root,remote):
    from .research_history import inspect
    name,artifact,binding,bundle=pending_candidate(registry,session,version)
    history=inspect(session,research_root)
    _,sealed=read_document(Path(research_root)/session['session_id']/'acceptance-history.json',2*1024*1024)
    accepted=status(registry,name)
    if history!=sealed or accepted['status']!='completed' or accepted['binding'].get('research_history_sha256')!=history['history_sha256']:
        raise ValueError('Require unchanged sealed research history bound to task acceptance')
    report=_checked(registry.root/name/'candidate-serving/serving.json')
    _,serving_binding=read_document(registry.root/name/'candidate-serving/binding.json',4*1024*1024)
    serving=check(registry,session,version,report['acceptance_dataset_path'],remote,
                  serving_binding['max_latency_seconds'],cached_only=True)
    if serving['status']!='serving_contract_checks_met' or not serving.get('userspace_snapshot_verified'):
        raise ValueError('Require successful serving checks with frozen CPU userspace')
    return {'task_binding':binding,'source_version':version,'history_sha256':history['history_sha256'],
            'acceptance_report_sha256':accepted['report_sha256'],'serving_record_sha256':serving['record_sha256'],
            'remote':remote,'research_root':str(Path(research_root).resolve()),
            'gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def promote(registry,session,version,research_root,remote):
    evidence=review(registry,session,version,research_root,remote)
    name=task_id(session['task_id']);new_version=digest(evidence)[:32]
    source=registry.root/name/version;folder=registry.root/name/new_version
    validation={'status':'scoped_holdout_and_serving_verified',
                'scope':'selected_task_research_ledger_and_frozen_acceptance_set',
                'complete_development_history_verified':False,'arbitrary_input_quality_guaranteed':False,
                'production_accepted':False}
    manifest={'task_id':name,'version':new_version,'parent_version':version,'session_id':session['session_id'],'status':'validated',
              'spec':{'kind':'candidate_bundle'},'validation':validation,
              'artifacts':{'bundle.json':sha(source/'bundle.json')},'delivery':evidence,'session':session}
    row=registry.db.execute('SELECT manifest_hash FROM versions WHERE version=?',(new_version,)).fetchone()
    if row:
        if sha(folder/'manifest.json')!=row[0] or json.loads((folder/'manifest.json').read_text(encoding='utf-8'))!=manifest:
            raise ValueError('Existing delivery version differs')
        return manifest
    if folder.exists():raise ValueError('Incomplete delivery retained; refusing overwrite')
    folder.mkdir(parents=True)
    (folder/'bundle.json').write_bytes((source/'bundle.json').read_bytes())
    atomic_json(folder/'manifest.json',manifest)
    with registry.db:
        registry.db.execute('INSERT INTO versions(task_id,version,status,manifest_hash) VALUES (?,?,?,?)',
                            (name,new_version,'validated',sha(folder/'manifest.json')))
    return manifest


def verify(registry,manifest):
    name=task_id(manifest['task_id']);folder=registry.root/name/manifest['version']
    if set(manifest['artifacts'])!={'bundle.json'} or sha(folder/'bundle.json')!=manifest['artifacts']['bundle.json']:
        raise ValueError('Delivery artifact integrity differs')
    evidence=manifest['delivery']
    actual=review(registry,manifest['session'],manifest['parent_version'],evidence['research_root'],evidence['remote'])
    if actual!=evidence:raise ValueError('Delivery acceptance or history evidence changed')
    return json.loads(base64.b64decode(json.loads((folder/'bundle.json').read_text(encoding='utf-8'))['contract_base64']))


def sample_input(registry,manifest,path,sample_id=None):
    from .contracts import validate_sample
    from .media import package_sample
    from .input_provenance import manifest as input_manifest
    contract=verify(registry,manifest)
    source=Path(path).resolve();_,sample=read_document(source,1024*1024)
    if sample_id is not None:sample['sample_id']=sample_id
    validate_sample(contract,sample)
    case={'sample':sample,'media':package_sample(contract,sample,source.parent,content_limit=512*1024)}
    rows=input_manifest(contract,[case])
    return sample,digest({'sample':sample,'input_manifest':rows}),rows


def infer(registry,manifest,path,expected_input_fingerprint=None,sample_id=None):
    from .candidate_inference import infer as execute
    sample,fingerprint,rows=sample_input(registry,manifest,path)
    if expected_input_fingerprint and fingerprint!=expected_input_fingerprint:
        raise ValueError('Input media changed after batch snapshot')
    if sample_id is not None:
        sample['sample_id']=sample_id
        rows[0]['sample_id']=sample_id
    evidence=manifest['delivery']
    request_id=digest({'version':manifest['version'],'sample':sample,'input_fingerprint':fingerprint})[:32]
    result=execute(registry,manifest['session'],manifest['parent_version'],request_id,[sample],
                   Path(path).resolve().parent,evidence['remote'],expected_input_manifest=rows)
    return {'task_id':manifest['task_id'],'version':manifest['version'],'kind':'candidate_bundle',
            'output':result['outputs'][0],'sample_id':sample['sample_id'],'acceptance':manifest['validation'],
            'execution_path':result['execution_path'],'execution_record_sha256':result['execution_record_sha256']}
