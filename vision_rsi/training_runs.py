"""Durable Training submissions and per-session GPU budget reservations."""
import json
import math
from pathlib import Path, PurePosixPath
import sqlite3
import time

from .remote import deploy_training, job_request
from .runner import digest

TERMINAL={'completed','failed','cancelled','timed_out'}


def remote_identity(remote):
    return {key:remote.get(key,default) for key,default in [('ssh_host',''),('ssh_port',22),('workspace',''),('python','python3')]}


class TrainingRuns:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
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
    def update(self,run_id,state,details,actual=None):
        with self.db:self.db.execute('UPDATE runs SET state=?,details=?,actual=? WHERE id=?',(state,json.dumps(details),actual,run_id))
        return self.get(run_id)
    def reserve(self,plan,remote):
        if plan['status']!='ready_to_submit': raise ValueError('Training plan is blocked')
        scheduler=plan['scheduler'];total=plan['contract']['budget']['gpu_hours']
        reserved=len(scheduler['gpu_devices'])*(scheduler['timeout_seconds']+5)/3600
        if not math.isfinite(reserved) or reserved<=0 or reserved>total: raise ValueError('Invalid Training reservation')
        run_id='train-'+digest({'session':plan['session_id'],'plan':plan['plan_id'],'remote':remote_identity(remote)})[:32]
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():
                self.db.commit();return self.get(run_id),False
            previous=self.db.execute('SELECT gpu_hours FROM budgets WHERE session=?',(plan['session_id'],)).fetchone()
            if previous and previous[0]!=total: raise ValueError('Session GPU budget changed; explicit budget revision support is pending')
            used=self.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM runs WHERE session=?',(plan['session_id'],)).fetchone()[0]
            if used+reserved>total+1e-12: raise ValueError('Session GPU budget exhausted by completed or reserved runs')
            self.db.execute('INSERT OR IGNORE INTO budgets VALUES (?,?)',(plan['session_id'],total))
            details={'plan_path':plan['plan_path'],'job_id':run_id,'phase':'reserved'}
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
    if action=='logs': return dict(record,log=response['log'])
    details=record['details'];details['remote_state']=response
    actual=None
    if response['status'] in TERMINAL:
        actual=response.get('gpu_hours')
        if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isfinite(actual) or actual<0:
            raise ValueError('Invalid remote GPU accounting; reservation retained')
    return store.update(run_id,response['status'],details,actual)
