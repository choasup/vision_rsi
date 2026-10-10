import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from vision_rsi.llm import request_payload
from vision_rsi.llm_usage import UsageLedger, CALL_ADMISSION_TRIGGER
from vision_rsi.paired_budget import api_quota, compare_budgets
from vision_rsi.runner import digest


class PairedBudgetTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.pair={};self.audits={};self.ledgers={}
        for arm in ('baseline','candidate'):
            llm={'model':'deepseek-flash','base_url':'https://fixture.invalid','usage_ledger':str(self.root/arm/'quota.sqlite3'),'usage_call_limit':1}
            bound={'session_id':arm,'campaign_id':'a'*64,'binding':{'contract':{'budget':{'gpu_hours':1}}},'execution_config':{'llm':llm}}
            self.pair[arm]=bound
            ledger=UsageLedger(llm['usage_ledger'],1);self.ledgers[arm]=ledger
            request={'messages':[{'role':'user','content':'Fixture only'}],'max_tokens':128}
            payload=request_payload(dict(llm,thinking='disabled'),request['messages'],128)
            key=ledger.reserve(json.dumps(payload).encode(),llm['model'])
            usage={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5};ledger.finish(key,usage)
            context={'llm':llm,'request_snapshot':request,'request_snapshot_sha256':digest(request)}
            response={'usage_record_id':key,'usage':usage}
            path=self.root/arm/bound['campaign_id']/'experiments/requests.sqlite3';path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE requests(context TEXT,state TEXT,response TEXT)')
                db.execute('INSERT INTO requests VALUES (?,?,?)',(json.dumps(context),'responded',json.dumps(response)))
            self.audits[arm]={'authorized_gpu_hours':1,'settled_gpu_hours':.5,'held_gpu_hours':0.,'gpu_accounting_settled':True,
                              'llm_admitted_or_uncertain_count':1,'known_llm_tokens':5}

    def compare(self):return compare_budgets(self.pair,self.audits,self.root,0,1)

    def test_actual_readonly_ledgers_link_payload_usage_and_equal_caps(self):
        before={arm:Path(ledger.path).read_bytes() for arm,ledger in self.ledgers.items()}
        result=self.compare()
        self.assertTrue(result['registered_dimensions_verified']);self.assertTrue(result['independent_equal_api_call_caps_verified'])
        self.assertFalse(result['full_resource_budgets_verified']);self.assertFalse(result['rsi_efficiency_verified'])
        self.assertEqual(before,{arm:Path(ledger.path).read_bytes() for arm,ledger in self.ledgers.items()})

    def test_payload_token_and_trigger_tampering_refused(self):
        ledger=self.ledgers['candidate']
        with ledger.connect() as db:original=db.execute('SELECT request_sha256,total_tokens FROM api_usage').fetchone()
        for sql in ("UPDATE api_usage SET request_sha256='wrong'",'UPDATE api_usage SET total_tokens=99','DROP TRIGGER api_usage_call_admission'):
            with ledger.connect() as db:db.execute(sql)
            with self.assertRaises(ValueError):api_quota(self.pair['candidate'],self.root,1,0)
            with ledger.connect() as db:
                db.execute('UPDATE api_usage SET request_sha256=?,total_tokens=?',original)
                db.execute(CALL_ADMISSION_TRIGGER)

    def test_unknown_extra_admission_and_missing_ledger_are_not_zero(self):
        ledger=self.ledgers['candidate']
        with ledger.connect() as db:db.execute("UPDATE api_usage SET status='uncertain'")
        self.assertFalse(self.compare()['registered_dimensions_verified'])
        path=Path(self.pair['candidate']['execution_config']['llm']['usage_ledger']);path.unlink()
        self.assertFalse(self.compare()['registered_dimensions_verified']);self.assertFalse(path.exists())

    def test_gpu_cap_and_audit_accounting_must_match(self):
        for change in ({'authorized_gpu_hours':True},{'settled_gpu_hours':1.1},{'held_gpu_hours':.1},
                       {'gpu_accounting_settled':False},{'llm_admitted_or_uncertain_count':0},{'known_llm_tokens':0}):
            original=dict(self.audits['candidate']);self.audits['candidate'].update(change)
            self.assertFalse(self.compare()['registered_dimensions_verified'],change)
            self.audits['candidate']=original

    def test_reused_usage_id_and_unattributed_rows_refused(self):
        bound=self.pair['candidate'];path=self.root/'candidate'/bound['campaign_id']/'experiments/requests.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:db.execute('INSERT INTO requests SELECT * FROM requests')
        with self.assertRaisesRegex(ValueError,'duplicated'):api_quota(bound,self.root,1,0)
        with closing(sqlite3.connect(path)) as db, db:db.execute('DELETE FROM requests')
        with self.assertRaisesRegex(ValueError,'Unattributed'):api_quota(bound,self.root,1,0)

    def test_zero_cap_requires_real_initialized_ledger_and_empty_requests(self):
        bound=self.pair['candidate'];bound['execution_config']['llm'].update(usage_call_limit=0,usage_ledger=str(self.root/'zero.sqlite3'))
        UsageLedger(bound['execution_config']['llm']['usage_ledger'],0)
        requests=self.root/'candidate'/bound['campaign_id']/'experiments/requests.sqlite3'
        with closing(sqlite3.connect(requests)) as db, db:db.execute('DELETE FROM requests')
        result=api_quota(bound,self.root,0,0)
        self.assertEqual(result['admitted_calls'],0);self.assertTrue(result['admission_rule_verified'])

    def test_foreign_arm_receipt_and_pre_registration_call_refused(self):
        bound=self.pair['candidate'];requests=self.root/'candidate'/bound['campaign_id']/'experiments/requests.sqlite3'
        with self.ledgers['baseline'].connect() as db:key=db.execute('SELECT id FROM api_usage').fetchone()[0]
        with closing(sqlite3.connect(requests)) as db, db:
            original=db.execute('SELECT response FROM requests').fetchone()[0]
            value=json.loads(original);value['usage_record_id']=key
            db.execute('UPDATE requests SET response=?',(json.dumps(value),))
        with self.assertRaisesRegex(ValueError,'foreign'):api_quota(bound,self.root,1,0)
        with closing(sqlite3.connect(requests)) as db, db:db.execute('UPDATE requests SET response=?',(original,))
        with self.assertRaisesRegex(ValueError,'time'):api_quota(bound,self.root,1,10**20)

    def test_different_names_for_one_quota_file_are_not_independent(self):
        left=self.ledgers['baseline'].path;right=self.ledgers['candidate'].path
        with self.ledgers['baseline'].connect() as db:key=db.execute('SELECT id FROM api_usage').fetchone()[0]
        right.unlink();right.hardlink_to(left)
        bound=self.pair['candidate'];requests=self.root/'candidate'/bound['campaign_id']/'experiments/requests.sqlite3'
        with closing(sqlite3.connect(requests)) as db, db:
            value=json.loads(db.execute('SELECT response FROM requests').fetchone()[0]);value['usage_record_id']=key
            db.execute('UPDATE requests SET response=?',(json.dumps(value),))
        result=self.compare()
        self.assertFalse(result['registered_dimensions_verified'])
        self.assertTrue(any('share one file' in value for value in result['missing_evidence']))
