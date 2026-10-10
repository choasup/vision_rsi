"""Shared API observations and optional ledger-wide call admission, not billing authority."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

CALL_ADMISSION_TRIGGER='''CREATE TRIGGER IF NOT EXISTS api_usage_call_admission BEFORE INSERT ON api_usage
    WHEN EXISTS (SELECT 1 FROM api_call_cap WHERE singleton=1 AND
                 (SELECT COUNT(*) FROM api_usage)>=calls)
    BEGIN SELECT RAISE(ABORT,'Project LLM call budget exhausted'); END'''


def admission_trigger_verified(db):
    row=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='api_usage_call_admission'").fetchone()
    def normalized(sql):return ''.join(sql.upper().replace('IF NOT EXISTS','').split())
    return bool(row and isinstance(row[0],str) and normalized(row[0])==normalized(CALL_ADMISSION_TRIGGER))


def ledger_path(value):
    if not isinstance(value,str) or not Path(value).is_absolute():
        raise ValueError('LLM usage_ledger requires an absolute local path')
    return Path(value)


def validate_call_limit(value):
    if type(value) is not int or not 0<=value<=1000000:
        raise ValueError('LLM usage_call_limit must be an integer in 0..1000000')


class UsageLedger:
    def __init__(self,path,call_limit=None):
        if call_limit is not None:validate_call_limit(call_limit)
        self.path=ledger_path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS api_usage (
                id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, model TEXT NOT NULL,
                created_ns INTEGER NOT NULL, ended_ns INTEGER, status TEXT NOT NULL,
                prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER)''')
            db.execute('CREATE TABLE IF NOT EXISTS api_call_cap (singleton INTEGER PRIMARY KEY CHECK(singleton=1), calls INTEGER NOT NULL)')
            if db.execute('SELECT calls FROM api_call_cap WHERE singleton=1').fetchone() and not admission_trigger_verified(db):
                raise ValueError('API admission trigger missing or changed; ledger not repaired or reset')
            db.execute(CALL_ADMISSION_TRIGGER)
            if not admission_trigger_verified(db):raise ValueError('API admission trigger changed')
            db.commit()
            if call_limit is not None:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT calls FROM api_call_cap WHERE singleton=1').fetchone()
                if row and row[0]!=call_limit:
                    raise ValueError('Project LLM call limit already bound; revision or reset is not supported')
                if not row:db.execute('INSERT INTO api_call_cap VALUES (1,?)',(call_limit,))

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def reserve(self,payload,model):
        identity=uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not admission_trigger_verified(db):raise ValueError('API admission trigger missing or changed')
                db.execute('INSERT INTO api_usage VALUES (?,?,?,?,NULL,?,NULL,NULL,NULL)',
                           (identity,hashlib.sha256(payload).hexdigest(),model,time.time_ns(),'pending'))
        except sqlite3.IntegrityError as error:
            if str(error)=='Project LLM call budget exhausted':
                raise ValueError('Project LLM call budget exhausted') from None
            raise
        return identity

    def finish(self,identity,usage=None):
        status='uncertain' if usage is None else 'responded'
        values=[usage.get(k) for k in ('prompt_tokens','completion_tokens','total_tokens')] if isinstance(usage,dict) else [None]*3
        if (any(type(n) is not int or not 0<=n<=2**53 for n in values)
                or values[0]+values[1]!=values[2]):values=[None]*3
        with self.connect() as db:
            cursor=db.execute('UPDATE api_usage SET ended_ns=?,status=?,prompt_tokens=?,completion_tokens=?,total_tokens=? WHERE id=? AND status=?',
                              (time.time_ns(),status,*values,identity,'pending'))
            if cursor.rowcount!=1:raise ValueError('LLM usage reservation missing or already settled')


def snapshot(path):
    path=ledger_path(path).resolve()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        db.execute('BEGIN')
        rows=db.execute('''SELECT model,status,COUNT(*),
            SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END),
            SUM(prompt_tokens),SUM(completion_tokens),SUM(total_tokens)
            FROM api_usage GROUP BY model,status ORDER BY model,status''').fetchall()
        cap=None
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_call_cap'").fetchone():
            row=db.execute('SELECT calls FROM api_call_cap WHERE singleton=1').fetchone()
            if row:
                validate_call_limit(row[0]);cap=row[0]
        trigger_verified=admission_trigger_verified(db)
    finally:db.close()
    groups=[dict(zip(('model','status','calls','unknown_token_calls','reported_prompt_tokens',
                       'reported_completion_tokens','reported_total_tokens'),row)) for row in rows]
    calls=sum(r['calls'] for r in groups)
    return {'ledger':str(path),'groups':groups,'calls':calls,
            'unknown_token_calls':sum(r['unknown_token_calls'] for r in groups),
            'project_call_limit':cap,'project_call_limit_enforced':cap is not None and trigger_verified,
            'admission_trigger_verified':trigger_verified,
            'remaining_project_calls':None if cap is None or not trigger_verified else max(0,cap-calls),
            'budget_enforced':False,'provider_billing_verified':False,'historical_backfill_complete':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',required=True)
    args=parser.parse_args(argv)
    try:report=snapshot(args.ledger)
    except (ValueError,sqlite3.Error,OSError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
