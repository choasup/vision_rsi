"""Read-only local release evidence audit; never infer remote availability."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from .acceptance import review
from .contracts import Sessions,issues
from .runner import digest
from .serving_acceptance import review_serving
from .task_adapters import training_adapter


def artifact_bytes(path,limit=16*1024*1024):
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Release artifact exceeds audit byte limit')
    return raw


def inspect(session_id,sessions,registry):
    session=Sessions(sessions,read_only=True).show(session_id)
    latest=session['versions'][-1] if session['versions'] else {}
    contract=latest.get('contract')
    errors=issues(contract) if contract else ['No defined task contract']
    if contract:
        adapter=training_adapter(contract)
        if not adapter['implementation_supported']:errors.extend(adapter['blockers'])
    if session.get('pending_request'):errors.append('Task requirement request remains pending')
    if latest.get('review_required'):errors.append('Task requirement change needs review')
    rows=[];root=Path(registry).resolve();database=root/'registry.sqlite3'
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            entries=db.execute('SELECT version,status,manifest_hash FROM versions WHERE task_id=? ORDER BY created DESC',(session['task_id'],)).fetchall()
        for version,status,expected in entries:
            row={'version':version,'registered_status':status,'local_evidence_passed':False}
            try:
                if not isinstance(version,str) or not re.fullmatch('[0-9a-f]{32}',version):raise ValueError('Invalid registered version')
                folder=root/session['task_id']/version
                raw=artifact_bytes(folder/'manifest.json',1024*1024)
                if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Manifest integrity failure')
                manifest=json.loads(raw)
                if manifest.get('task_id')!=session['task_id'] or manifest.get('version')!=version:raise ValueError('Registered manifest identity mismatch')
                if manifest.get('session_id')!=session_id:raise ValueError('Capability belongs to a different training session')
                if manifest.get('spec',{}).get('kind')!='coco_detection':raise ValueError('This audit supports COCO serving evidence only')
                if status!='validated' or manifest.get('status')!='validated':raise ValueError('Serving validation remains pending')
                if digest(manifest['endpoint']['contract'])!=digest(contract):raise ValueError('Capability contract differs from current task')
                required={'plan.json','receipt.json','inference.py','serving-report.json'}
                if set(manifest['artifacts'])!=required:raise ValueError('Capability artifact set mismatch')
                artifacts={}
                for name,checksum in manifest['artifacts'].items():
                    data=artifact_bytes(folder/name)
                    if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError('Artifact integrity failure: '+name)
                    if name.endswith('.json'):artifacts[name]=json.loads(data)
                plan=artifacts['plan.json'];receipt=artifacts['receipt.json']
                if plan.get('session_id')!=session_id or plan.get('task_id')!=session['task_id']:raise ValueError('Training plan task mismatch')
                if receipt.get('run_id')!=manifest.get('training_run_id'):raise ValueError('Training receipt run mismatch')
                if digest(plan['contract'])!=digest(contract):raise ValueError('Training contract mismatch')
                training=review(plan,receipt)
                if not training['passed']:raise ValueError('Training acceptance failed: '+'; '.join(training['reasons']))
                if training['checkpoint_sha256']!=manifest['endpoint']['checkpoint_sha256']:raise ValueError('Serving checkpoint differs from accepted training')
                if digest(training['training_identity'])!=manifest['endpoint']['training_identity_hash']:raise ValueError('Serving training identity mismatch')
                if manifest['endpoint']['recipe']!=plan['recipe'] or manifest['endpoint']['source_hashes']!=plan['source_hashes']:
                    raise ValueError('Serving recipe or source identity mismatch')
                serving=review_serving(manifest,artifacts['serving-report.json'])
                row.update(local_evidence_passed=True,serving_box_AP=serving['box_AP'])
            except (ValueError,KeyError,TypeError,OSError) as error:row['blocker']=str(error)
            rows.append(row)
    ready=not errors and any(row['local_evidence_passed'] for row in rows)
    if not rows:errors.append('No registered capability for this task')
    elif not any(row['local_evidence_passed'] for row in rows):errors.append('No capability passed current-session training and serving evidence checks')
    return {'session_id':session_id,'task_id':session['task_id'],'contract_version':latest.get('version'),
        'status':'local_evidence_ready_for_test' if ready else 'blocked','local_release_evidence_complete':ready,
        'blockers':errors,'versions':rows,'read_only':True,'remote_called':False,'llm_called':False,
        'remote_availability_verified':False,'inference_executed':False,'rsi_efficiency_verified':False,
        'scope':'Local COCO release artifact audit only; not live test execution, new-machine certification or whole-Agent launch completion.'}
