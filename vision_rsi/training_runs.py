"""Durable Training submissions and per-session GPU budget reservations."""
import json
import math
from pathlib import Path, PurePosixPath
import sqlite3
import time
from urllib.parse import quote

from .remote import deploy_training, job_request
from .training_preflight import check as resource_preflight
from .runner import digest

TERMINAL={'completed','failed','cancelled','timed_out'}


def remote_identity(remote):
    return {key:remote.get(key,default) for key,default in [('ssh_host',''),('ssh_port',22),('workspace',''),('python','python3')]}


class TrainingRuns:
    def __init__(self,root,read_only=False):
        self.root=Path(root)
        if read_only:
            path=self.root/'training-runs.sqlite3'
            if not path.is_file():raise ValueError('Training ledger missing')
            self.db=sqlite3.connect('file:'+quote(str(path.resolve()).replace('\\','/'),safe='/:')+'?mode=ro',uri=True,timeout=10)
            return
        self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'training-runs.sqlite3',timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS budgets(session TEXT PRIMARY KEY,gpu_hours REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session TEXT,plan TEXT,remote TEXT,reserved REAL,actual REAL,state TEXT,details TEXT,created REAL)')
        self.db.commit()
    def close(self): self.db.close()
    def get(self,run_id):
        row=self.db.execute('SELECT id,session,plan,remote,reserved,actual,state,details FROM runs WHERE id=?',(run_id,)).fetchone()
        if not row: raise ValueError('Unknown Training run')
        return dict(zip(('run_id','session_id','plan_id','remote','reserved_gpu_hours','actual_gpu_hours','status','details'),
                        [*row[:3],json.loads(row[3]),*row[4:7],json.loads(row[7])]))
    def list(self,session):
        return [self.get(row[0]) for row in self.db.execute('SELECT id FROM runs WHERE session=? ORDER BY created',(session,)).fetchall()]
    def remaining(self,session,total):
        if isinstance(total,bool) or not isinstance(total,(int,float)) or not math.isfinite(total) or total<=0:raise ValueError('Invalid session GPU budget')
        frozen=self.db.execute('SELECT gpu_hours FROM budgets WHERE session=?',(session,)).fetchone()
        if frozen and frozen[0]!=total:raise ValueError('Session GPU budget changed; no implicit authorization increase')
        used=self.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM runs WHERE session=?',(session,)).fetchone()[0]
        return max(0,total-used)
    def update(self,run_id,state,details,actual=None):
        with self.db:self.db.execute('UPDATE runs SET state=?,details=?,actual=? WHERE id=?',(state,json.dumps(details),actual,run_id))
        return self.get(run_id)
    def reserve(self,plan,remote,attempt=None,cap_to_remaining=False,active_output=None):
        if plan['status']!='ready_to_submit': raise ValueError('Training plan is blocked')
        from .training_plan import require_supported_budget
        require_supported_budget(plan['contract'])
        scheduler=dict(plan['scheduler']);total=plan['contract']['budget']['gpu_hours']
        identity={'session':plan['session_id'],'plan':plan['plan_id'],'remote':remote_identity(remote)}
        if attempt is not None: identity['attempt']=attempt
        run_id='train-'+digest(identity)[:32]
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():
                self.db.commit();return self.get(run_id),False
            if active_output:
                pending=self.db.execute('SELECT details FROM runs WHERE session=? AND actual IS NULL',(plan['session_id'],)).fetchall()
                if any(json.loads(row[0]).get('output_directory')==active_output for row in pending):
                    raise ValueError('Another active or uncertain attempt owns this Training output')
            previous=self.db.execute('SELECT gpu_hours FROM budgets WHERE session=?',(plan['session_id'],)).fetchone()
            if previous and previous[0]!=total: raise ValueError('Session GPU budget changed; explicit budget revision support is pending')
            used=self.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM runs WHERE session=?',(plan['session_id'],)).fetchone()[0]
            devices=len(scheduler['gpu_devices'])
            if cap_to_remaining:
                if not devices: raise ValueError('GPU devices required for Training resume')
                scheduler['timeout_seconds']=min(scheduler['timeout_seconds'],math.floor((total-used)*3600/devices)-5)
            reserved=devices*(scheduler['timeout_seconds']+5)/3600
            if not math.isfinite(reserved) or reserved<=0 or scheduler['timeout_seconds']<=0 or reserved>total:
                raise ValueError('Insufficient remaining Training budget')
            if used+reserved>total+1e-12: raise ValueError('Session GPU budget exhausted by completed or reserved runs')
            self.db.execute('INSERT OR IGNORE INTO budgets VALUES (?,?)',(plan['session_id'],total))
            details={'plan_path':plan['plan_path'],'job_id':run_id,'phase':'reserved','scheduler':scheduler}
            if active_output: details['output_directory']=active_output
            self.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,NULL,?,?,?)',(run_id,plan['session_id'],plan['plan_id'],json.dumps(remote_identity(remote)),reserved,'reserved',json.dumps(details),time.time()))
            self.db.commit();return self.get(run_id),True
        except Exception:self.db.rollback();raise


def submit(plan,remote,store):
    if plan['status']=='blocked': return plan
    record,created=store.reserve(plan,remote)
    if not created: return dict(record,reused=True)  # Never relaunch an uncertain/active/terminal run.
    run_id=record['run_id'];details=record['details']
    try:
        deployment=deploy_training(remote,plan)
        if not deployment['dependencies_ready']: raise RuntimeError('Remote pycocotools missing; install pinned optional dependency before GPU submission')
        details['deployment']=deployment
        details['resource_preflight']=resource_preflight(remote,deployment,plan)
        output=str(PurePosixPath(remote['workspace'])/'training'/plan['task_id']/run_id)
        argv=[remote.get('python','python3'),'-m','torch.distributed.run','--standalone',
              '--nproc-per-node='+str(plan['recipe']['world_size']),deployment['entry'],'--recipe',deployment['recipe'],'--output',output]
        spec=dict(plan['scheduler'],argv=argv,gpu_hours_budget=record['reserved_gpu_hours'])
        from .jobs import validate_spec
        validate_spec(spec)
        details.update(spec=spec,output_directory=output,phase='submitting')
        store.update(run_id,'submitting',details)
    except Exception as error:
        details['error']=type(error).__name__+': '+str(error)
        store.update(run_id,'deployment_failed',details,actual=0)
        raise
    try:
        response=job_request(remote,'submit',run_id,spec)
        details.update(submission=response,phase='submitted')
        return store.update(run_id,'submitted',details)
    except Exception as error:
        # The SSH response can be lost after the server started the job. Keep
        # reservation and stable ID; reconcile through status, never relaunch.
        details['error']=type(error).__name__+': '+str(error)
        store.update(run_id,'submission_uncertain',details)
        raise


def observe(run_id,remote,store,action='status'):
    if action not in ('status','logs','cancel'): raise ValueError('Unknown Training observation action')
    record=store.get(run_id)
    if record['remote']!=remote_identity(remote): raise ValueError('Training run belongs to another SSH destination')
    response=job_request(remote,action,run_id)
    log=None
    if action=='logs':
        log=response['log']
        # Logs are diagnostic text, never authoritative process evidence.
        # Reconcile the same job before releasing any budget reservation.
        response=job_request(remote,'status',run_id)
    details=record['details'];details['remote_state']=response
    actual=None
    if response['status'] in TERMINAL:
        actual=response.get('gpu_hours')
        if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isfinite(actual) or actual<0:
            raise ValueError('Invalid remote GPU accounting; reservation retained')
    updated=store.update(run_id,response['status'],details,actual)
    return dict(updated,log=log) if action=='logs' else updated


def collect(run_id,remote,store):
    """Reconcile the process, retain the raw receipt, then review task evidence."""
    from .acceptance import review
    from .remote import collect_training
    from .runner import atomic_json
    record=observe(run_id,remote,store)
    if record['status']!='completed': raise ValueError('Only completed Training processes can be collected')
    details=record['details']
    plan=json.loads(Path(details['plan_path']).read_text(encoding='utf-8'))
    if digest(plan)!=record['plan_id']: raise ValueError('Local frozen Training plan changed')
    receipt=collect_training(remote,run_id,details['output_directory'],details.get('output_run_id',run_id))
    if receipt['run_id']!=run_id: raise ValueError('Receipt belongs to another run')
    identity=digest(receipt)
    folder=store.root/'artifacts'/run_id/identity;folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'receipt.json'
    if destination.exists():
        if json.loads(destination.read_text())!=receipt: raise ValueError('Local receipt identity conflict')
    else: atomic_json(destination,receipt)
    try: verdict=review(plan,receipt)
    except (ValueError,KeyError,TypeError) as error:
        verdict={'status':'rejected','passed':False,'reason':type(error).__name__+': '+str(error),'capability_registered':False}
    atomic_json(folder/'review.json',verdict)
    details['acceptance_review']=verdict;details['receipt_path']=str(destination.resolve())
    return store.update(run_id,record['status'],details,record['actual_gpu_hours'])



def resume(run_id,remote,store):
    from .remote import collect_training
    from .jobs import validate_spec
    parent=observe(run_id,remote,store)
    if parent['status'] not in TERMINAL: raise ValueError('Original Training attempt is active, lost or uncertain; cannot resume')
    original=parent['details'];deployment=original.get('deployment',{})
    if deployment.get('resume_protocol',1)<2:
        raise ValueError('Frozen development bundle lacks checkpoint-hash resume support; no code upgrade performed')
    base=json.loads(Path(original['plan_path']).read_text(encoding='utf-8'))
    if digest(base)!=parent['plan_id']: raise ValueError('Frozen Training plan changed')
    from .training_plan import require_supported_budget
    require_supported_budget(base['contract'])
    output=original['output_directory'];origin=original.get('output_run_id',run_id)
    checkpoint=collect_training(remote,run_id,output,origin,action='checkpoint')
    progress_status=checkpoint['progress'].get('status')
    if progress_status=='evaluated': raise ValueError('Training already evaluated; use collect instead of resume')
    if progress_status not in ('training','interrupted','evaluating','interrupted_evaluation'):
        raise ValueError('Unrecognized checkpoint progress state')
    checksum=checkpoint['checkpoint_sha256']
    if not isinstance(checksum,str) or len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError('Invalid resume checkpoint identity')
    plan=dict(base,plan_id=parent['plan_id'],plan_path=original['plan_path'])
    record,created=store.reserve(plan,remote,attempt={'parent_run_id':run_id,'checkpoint_sha256':checksum},cap_to_remaining=True,active_output=output)
    if not created: return dict(record,reused=True)
    new_id=record['run_id'];details=record['details']
    try:
        details['resource_preflight']=resource_preflight(remote,deployment,base,checkpoint={'directory':output,'sha256':checksum})
        argv=[value for value in original['spec']['argv']]
        if '--checkpoint-sha256' in argv:
            index=argv.index('--checkpoint-sha256');del argv[index:index+2]
        if '--resume' not in argv: argv.append('--resume')
        argv+=['--checkpoint-sha256',checksum]
        spec=dict(details['scheduler'],argv=argv,gpu_hours_budget=record['reserved_gpu_hours'])
        validate_spec(spec)
        details.update(parent_run_id=run_id,output_run_id=origin,output_directory=output,
                       checkpoint_sha256=checksum,deployment=deployment,spec=spec,phase='submitting')
        store.update(new_id,'submitting',details)
    except Exception as error:
        details['error']=type(error).__name__+': '+str(error)
        store.update(new_id,'resume_preflight_failed',details,actual=0);raise
    try:
        response=job_request(remote,'submit',new_id,spec)
        details.update(submission=response,phase='submitted')
        return store.update(new_id,'submitted',details)
    except Exception as error:
        details['error']=type(error).__name__+': '+str(error)
        store.update(new_id,'submission_uncertain',details);raise
