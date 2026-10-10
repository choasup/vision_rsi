"""Atomic LLM-call admission for an adapter-repair lineage, including history.

This is not a global Agent budget: clarification, strategy research and GPU
training have separate records. Unknown outcomes retain one call reservation.
Known pre-dispatch refusals remain auditable but do not consume a lineage call.
"""
import json
from pathlib import Path
import re

from .runner import digest


def lineage_root(store,candidate_id):
    seen=set()
    for _ in range(100):
        if not isinstance(candidate_id,str) or not re.fullmatch('[0-9a-f]{64}',candidate_id) or candidate_id in seen:
            raise ValueError('Invalid or cyclic adapter repair lineage')
        seen.add(candidate_id)
        record=store.verify(json.loads((store.root/candidate_id/'candidate.json').read_text(encoding='utf-8')))
        context=record['identity']['context']
        if context.get('kind')!='adapter_contract_repair_v1':return candidate_id
        candidate_id=context.get('parent_candidate_id')
    raise ValueError('Adapter repair lineage exceeds audit depth')


def limit(contract):
    budget=contract.get('budget') or {}
    value=budget.get('adapter_repair_calls',budget.get('llm_calls'))
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=10000:
        raise ValueError('Adapter repair requires explicit integer budget.adapter_repair_calls in 0..10000')
    return value


def admit_contract(contract):
    budget=contract.get('budget') or {}
    if 'adapter_repair_calls' not in budget:raise ValueError('Explicit budget.adapter_repair_calls required; legacy llm_calls is audit-only')
    limit(contract)
    if 'llm_calls' in budget:raise ValueError('Global LLM call budget is not reconciled across Agent stages; repair call not admitted')


def history(store):
    """Backfill pre-ledger attempts; missing evidence cannot erase spending."""
    from .adapter_repair import failure_context
    rows=store.db.execute('SELECT id,identity FROM requests LIMIT 10001')
    result=[]
    for index,(request_id,encoded) in enumerate(rows):
        if index>=10000:raise ValueError('Research request history exceeds bounded budget audit')
        identity=json.loads(encoded)
        if identity.get('kind')!='adapter_contract_repair_v1':continue
        parent=identity['parent_candidate_id'];root=lineage_root(store,parent)
        found=None
        for path in (store.root/parent/'checks').glob('*.adapter.json'):
            report=json.loads(path.read_text(encoding='utf-8'))
            if digest(report)==identity['parent_report_sha256']:
                found=path;break
        if found is None:raise ValueError('Historical repair feedback missing; call occupancy cannot be reconciled')
        report,_,_,_=failure_context(store,found,identity['module'],identity['function'])
        result.append((request_id,root,digest(report['contract']),limit(report['contract'])))
    return result


def reconcile(store,parent_id,contract,request_id=None,identity=None):
    if request_id is not None:admit_contract(contract)
    root=lineage_root(store,parent_id);contract_sha=digest(contract);maximum=limit(contract)
    old=history(store)
    store.db.execute('CREATE TABLE IF NOT EXISTS repair_budgets(root TEXT PRIMARY KEY,contract TEXT NOT NULL,calls_limit INTEGER NOT NULL)')
    store.db.execute('CREATE TABLE IF NOT EXISTS repair_calls(request_id TEXT PRIMARY KEY,root TEXT NOT NULL,contract TEXT NOT NULL)')
    store.db.commit()
    store.db.execute('BEGIN IMMEDIATE')
    try:
        def bind(root_id,sha,calls_limit):
            row=store.db.execute('SELECT contract,calls_limit FROM repair_budgets WHERE root=?',(root_id,)).fetchone()
            if row and row!=(sha,calls_limit):raise ValueError('Repair lineage contract/call budget changed; no implicit reset or increase')
            store.db.execute('INSERT OR IGNORE INTO repair_budgets VALUES (?,?,?)',(root_id,sha,calls_limit))
        for prior,prior_root,sha,calls_limit in old:
            bind(prior_root,sha,calls_limit)
            known=store.db.execute('SELECT root,contract FROM repair_calls WHERE request_id=?',(prior,)).fetchone()
            if known and known!=(prior_root,sha):raise ValueError('Repair call lineage identity changed')
            store.db.execute('INSERT OR IGNORE INTO repair_calls VALUES (?,?,?)',(prior,prior_root,sha))
        bind(root,contract_sha,maximum)
        used=store.db.execute("SELECT COUNT(*) FROM repair_calls c LEFT JOIN requests r ON r.id=c.request_id WHERE c.root=? AND (r.state IS NULL OR r.state!='not_dispatched')",(root,)).fetchone()[0]
        if request_id is not None:
            if used>=maximum:raise ValueError('Adapter repair LLM call budget exhausted; unknown outcomes retain occupancy')
            if identity.get('parent_candidate_id')!=parent_id:raise ValueError('Repair reservation parent differs')
            store.db.execute('INSERT INTO requests VALUES (?,?,?,NULL)',(request_id,json.dumps(identity),'reserved'))
            store.db.execute('INSERT INTO repair_calls VALUES (?,?,?)',(request_id,root,contract_sha))
        store.db.commit()
    except Exception:
        store.db.rollback();raise
    rows=store.db.execute('SELECT c.request_id,r.state FROM repair_calls c LEFT JOIN requests r ON r.id=c.request_id WHERE c.root=? ORDER BY c.request_id',(root,)).fetchall()
    if any(state is None for _,state in rows):raise ValueError('Repair request record missing; reservation retained')
    occupied=sum(state!='not_dispatched' for _,state in rows)
    return {'scope':'adapter-repair lineage only; excludes clarification, strategy research and GPU training',
            'budget_field':'adapter_repair_calls' if 'adapter_repair_calls' in contract['budget'] else 'legacy_llm_calls_audit_only',
            'new_calls_authorized':'adapter_repair_calls' in contract['budget'] and 'llm_calls' not in contract['budget'] and occupied<maximum,
            'global_llm_budget_verified':False,
            'root_candidate_id':root,'contract_sha256':contract_sha,'llm_calls_limit':maximum,
            'occupied_calls':occupied,'not_dispatched_calls':sum(state=='not_dispatched' for _,state in rows),'responded_calls':sum(state=='responded' for _,state in rows),
            'unsettled_calls':sum(state not in ('responded','not_dispatched') for _,state in rows),'remaining_calls':max(0,maximum-occupied)}
