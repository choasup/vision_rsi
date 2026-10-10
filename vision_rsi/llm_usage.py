"""Shared durable API usage observations, not a budget or billing authority."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def ledger_path(value):
    if not isinstance(value,str) or not Path(value).is_absolute():
        raise ValueError('LLM usage_ledger requires an absolute local path')
    return Path(value)


class UsageLedger:
    def __init__(self,path):
        self.path=ledger_path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS api_usage (
                id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, model TEXT NOT NULL,
                created_ns INTEGER NOT NULL, ended_ns INTEGER, status TEXT NOT NULL,
                prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER)''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def reserve(self,payload,model):
        identity=uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO api_usage VALUES (?,?,?,?,NULL,?,NULL,NULL,NULL)',
                       (identity,hashlib.sha256(payload).hexdigest(),model,time.time_ns(),'pending'))
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
    finally:db.close()
    groups=[dict(zip(('model','status','calls','unknown_token_calls','reported_prompt_tokens',
                       'reported_completion_tokens','reported_total_tokens'),row)) for row in rows]
    return {'ledger':str(path),'groups':groups,'calls':sum(r['calls'] for r in groups),
            'unknown_token_calls':sum(r['unknown_token_calls'] for r in groups),
            'budget_enforced':False,'provider_billing_verified':False,'historical_backfill_complete':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',required=True)
    args=parser.parse_args(argv)
    try:report=snapshot(args.ledger)
    except (ValueError,sqlite3.Error,OSError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
