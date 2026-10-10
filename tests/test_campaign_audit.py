import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_acceptance import evidence
from vision_rsi.campaign_audit import audit
from vision_rsi.runner import digest
from vision_rsi.training_runs import TrainingRuns


class CampaignAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.ledger=self.root/'ledger';self.ledger.mkdir();(self.ledger/'training-runs.sqlite3').touch()
        # Fabricated full-shape metadata tests verifier logic, not COCO quality.
        parent,receipt=evidence(42);parent['contract']['budget']={'gpu_hours':1};parent['session_id']='session'
        pp=self.root/'plan.json';pp.write_text(json.dumps(parent))
        receipt['run_id']='train-'+'a'*32;rp=self.root/'receipt.json';rp.write_text(json.dumps(receipt))
        self.receipt=rp
        self.record={'run_id':receipt['run_id'],'status':'completed','reserved_gpu_hours':.2,'actual_gpu_hours':.1,
                     'plan_id':digest(parent),'details':{'plan_path':str(pp),'receipt_path':str(rp)}}
        binding={'session_id':'session','contract':parent['contract'],'run_store':str(self.ledger.resolve()),'policy':None}
        self.cid=digest(binding);self.folder=self.root/'campaigns/session'/self.cid;self.folder.mkdir(parents=True)
        self.state={'campaign_id':self.cid,'binding':binding,'history':[self.row('submit',{'run_id':self.record['run_id']})],'intent':None,'run_id':self.record['run_id']}
        self.save()
        self.patch=patch('vision_rsi.campaign_audit.TrainingRuns');self.store=self.patch.start();self.addCleanup(self.patch.stop)
        self.store.return_value.list.return_value=[self.record]
    @staticmethod
    def row(kind,result):return {'action':{'kind':kind},'result':result,'policy_elapsed_seconds':.01,'tool_attempts':[{'status':'completed','elapsed_seconds':2}]}
    def save(self):(self.folder/'state.json').write_text(json.dumps(self.state))
    def audit(self):return audit('session',self.cid,self.root/'campaigns',self.ledger)

    def test_recomputes_metric_and_cost_without_rsi_claim(self):
        result=self.audit()
        self.assertEqual(result['best_verified_real_box_AP'],42)
        self.assertEqual(result['settled_gpu_hours'],.1);self.assertEqual(result['held_gpu_hours'],0)
        self.assertTrue(result['evidence_complete_for_review'])
        self.assertFalse(result['rsi_efficiency_verified']);self.assertFalse(result['agent_adopted'])
        self.store.assert_called_once_with(self.ledger,read_only=True)

    def test_tampered_receipt_and_unknown_timing_do_not_become_zero_cost(self):
        self.state['history'][0].pop('tool_attempts');self.save()
        result=self.audit();self.assertFalse(result['action_timing_complete'])
        value=json.loads(self.receipt.read_text());value['reports']['evaluation.json']['sha256']='0'*64;self.receipt.write_text(json.dumps(value))
        result=self.audit();self.assertIsNone(result['best_verified_real_box_AP'])
        self.assertFalse(result['evidence_complete_for_review'])

    def test_unknown_reservations_and_other_campaign_runs_remain_accounted(self):
        extra=copy.deepcopy(self.record);extra.update(run_id='other-run',status='submission_uncertain',actual_gpu_hours=None)
        self.store.return_value.list.return_value=[self.record,extra]
        result=self.audit();self.assertEqual(result['held_gpu_hours'],.2)
        self.assertEqual(result['unattributed_run_ids'],['other-run'])
        self.assertFalse(result['gpu_accounting_settled']);self.assertFalse(result['evidence_complete_for_review'])

    def test_llm_cost_is_from_persisted_usage_and_unknown_is_flagged(self):
        self.state['history'].append(self.row('propose_experiment',{'status':'proposal_rejected'}));self.save()
        folder=self.folder/'experiments';folder.mkdir();db=sqlite3.connect(folder/'requests.sqlite3')
        db.execute('CREATE TABLE requests(id TEXT,state TEXT,response TEXT)')
        db.execute('INSERT INTO requests VALUES (?,?,?)',('request','responded',json.dumps({'usage':{'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}})));db.commit()
        result=self.audit();self.assertTrue(result['llm_usage_complete']);self.assertEqual(result['known_llm_tokens'],8)
        db.execute('UPDATE requests SET state=?,response=NULL',('reserved',));db.commit();db.close()
        result=self.audit();self.assertFalse(result['llm_usage_complete']);self.assertFalse(result['evidence_complete_for_review'])

    def test_readonly_ledger_rejects_writes_and_does_not_create_missing_db(self):
        folder=self.root/'actual-ledger';writer=TrainingRuns(folder);writer.close()
        reader=TrainingRuns(folder,read_only=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):reader.db.execute('DELETE FROM budgets')
        finally:reader.close()
        missing=self.root/'missing-ledger'
        with self.assertRaises(ValueError):TrainingRuns(missing,read_only=True)
        self.assertFalse(missing.exists())
