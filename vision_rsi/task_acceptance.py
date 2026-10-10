"""Single candidate acceptance slot per task in the authoritative registry."""
import base64
import hashlib
import json
from pathlib import Path
import re

from .candidate_bundle import verify
from .capability import task_id, sha
from .campaign import lease
from .event_eval import read_document
from .runner import digest


def _schema(registry):
    with registry.db:
        registry.db.execute('CREATE TABLE IF NOT EXISTS candidate_acceptance_slots(task_id TEXT PRIMARY KEY, binding TEXT NOT NULL, status TEXT NOT NULL, report_hash TEXT)')


def status(registry, name):
    name = task_id(name)
    if registry.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_acceptance_slots'").fetchone() is None:
        return {'task_id':name, 'status':'not_reserved', 'production_accepted':False}
    row = registry.db.execute('SELECT binding,status,report_hash FROM candidate_acceptance_slots WHERE task_id=?',(name,)).fetchone()
    if row is None:
        return {'task_id':name, 'status':'not_reserved', 'production_accepted':False}
    if row[1] not in ('reserved','completed'):raise ValueError('Invalid task acceptance state')
    binding = json.loads(row[0])
    return {'task_id':name, 'status':row[1], 'binding':binding, 'report_sha256':row[2],
            'report_path':str(registry.root/name/'candidate-acceptance'/'acceptance.json'), 'production_accepted':False}


def accept(registry, session, version, dataset_path, development_paths, remote):
    """Reserve before dispatch; neither changed versions nor sessions reset the slot."""
    versions = session.get('versions',[])
    if session.get('pending_request') or not versions or versions[-1].get('review_required'):
        raise ValueError('Resolve task requirements before candidate acceptance')
    name = task_id(session['task_id'])
    if not isinstance(version,str) or not re.fullmatch('[0-9a-f]{32}',version):
        raise ValueError('Require a registered candidate version')
    row = registry.db.execute('SELECT status,manifest_hash FROM versions WHERE task_id=? AND version=?',(name,version)).fetchone()
    if row is None or row[0] != 'pending_independent_validation':
        raise ValueError('No pending task-bound candidate version')
    folder = registry.root/name/version
    if sha(folder/'manifest.json') != row[1]:raise ValueError('Candidate manifest integrity differs')
    _, delivery = read_document(folder/'manifest.json',2*1024*1024)
    expected = {'session_id':session['session_id'],'task_id':name,'contract_version':len(versions),
                'contract_sha256':digest(versions[-1]['contract'])}
    binding = delivery.get('task_binding',{})
    if any(binding.get(key)!=value for key,value in expected.items()):
        raise ValueError('Candidate belongs to another task contract or session')
    if delivery.get('task_id')!=name or delivery.get('version')!=version or delivery.get('spec')!={'kind':'candidate_bundle'} or delivery.get('status')!=row[0]:
        raise ValueError('Invalid pending candidate delivery')
    if set(delivery.get('artifacts',{}))!={'bundle.json'} or sha(folder/'bundle.json')!=delivery['artifacts']['bundle.json']:
        raise ValueError('Candidate artifact integrity differs')
    bundle = verify(folder/'bundle.json')
    if bundle['bundle_id']!=binding.get('bundle_id') or digest(json.loads(base64.b64decode(bundle['contract_base64'])))!=expected['contract_sha256']:
        raise ValueError('Candidate bundle differs from registered task')
    if not development_paths or len(development_paths)>128:raise ValueError('Require 1..128 development records')
    from .bundle_acceptance import prepare, accept as evaluate
    prepared = prepare(folder/'bundle.json',dataset_path,development_paths,remote)
    request = {'task_binding':binding, 'version':version,
               'acceptance_binding_sha256':digest(prepared['binding']),
               'task_gate_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    encoded = json.dumps(request,sort_keys=True,ensure_ascii=False,allow_nan=False)
    _schema(registry)
    # DB uniqueness scopes the reservation to task ID, not caller's output directory.
    with registry.db:
        registry.db.execute('INSERT OR IGNORE INTO candidate_acceptance_slots VALUES (?,?,?,NULL)',(name,encoded,'reserved'))
        saved = registry.db.execute('SELECT binding FROM candidate_acceptance_slots WHERE task_id=?',(name,)).fetchone()
        if saved[0]!=encoded:raise ValueError('Task acceptance is already reserved; another candidate, dataset or session cannot reset it')
    root = registry.root/name/'candidate-acceptance'; root.mkdir(parents=True,exist_ok=True)
    with lease(root/'task.lock',owner='Task candidate acceptance'):
        before = status(registry,name)
        report = evaluate(folder/'bundle.json',dataset_path,development_paths,remote,root,
                          expected_binding_sha256=request['acceptance_binding_sha256'])
        if before['status']=='completed' and before['report_sha256']!=report['report_sha256']:
            raise ValueError('Task acceptance report changed')
        with registry.db:
            registry.db.execute("UPDATE candidate_acceptance_slots SET status='completed',report_hash=? WHERE task_id=? AND binding=?",
                                (report['report_sha256'],name,encoded))
        return dict(report,task_id=name,version=version,task_acceptance_slot=str(root),
                    task_acceptance_reserved=True,task_wide_registry_scope=True)
