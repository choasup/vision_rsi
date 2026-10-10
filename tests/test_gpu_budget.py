import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import GPU_BUDGET_QUESTION,Sessions
from vision_rsi.requirements import changes
from vision_rsi.training_cli import main


class InitialGpuBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Sessions(self.root/'sessions')
        self.sid=self.store.create('inspection','Original task')['session_id']
        self.contract=json.loads(Path('examples/interface-contract.json').read_text(encoding='utf-8'))
        self.contract['acceptance']['threshold']=60
        self.contract['budget']=None;self.contract['open_questions']=[GPU_BUDGET_QUESTION]
        self.store.define(self.sid,self.contract)

    def test_only_explicit_budget_changes_and_unrelated_question_is_retained(self):
        original=copy.deepcopy(self.contract);original['open_questions'].append('Which defect labels are required?')
        before=self.store.define(self.sid,original)
        result=self.store.set_gpu_budget(self.sid,32)
        current=result['versions'][-1]['contract']
        self.assertEqual([r['path'] for r in changes(original,current)],['budget'])
        self.assertEqual(current['open_questions'],['Which defect labels are required?'])
        self.assertEqual(result['versions'][:-1],before['versions'])
        self.assertEqual(result['versions'][-1]['origin'],'user_gpu_budget')
        self.assertEqual(current['acceptance']['threshold'],60)
        self.assertEqual(self.store.set_gpu_budget(self.sid,32),result)
        with self.assertRaisesRegex(ValueError,'cannot revise or reset'):self.store.set_gpu_budget(self.sid,64)
        self.assertEqual(self.store.show(self.sid),result)

    def test_invalid_values_pending_request_and_review_cannot_change_authority(self):
        original=self.store.show(self.sid)
        for value in (True,0,-1,float('nan'),float('inf'),1e308,'32'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.set_gpu_budget(self.sid,value)
            self.assertEqual(self.store.show(self.sid),original)
        with self.store.db() as db:db.execute('UPDATE sessions SET pending=1 WHERE id=?',(self.sid,))
        with self.assertRaisesRegex(ValueError,'in progress'):self.store.set_gpu_budget(self.sid,32)
        with self.store.db() as db:
            versions=copy.deepcopy(original['versions']);versions[-1]['review_required']=[{'path':'acceptance.threshold'}]
            db.execute('UPDATE sessions SET pending=0,versions=? WHERE id=?',(json.dumps(versions),self.sid))
        with self.assertRaisesRegex(ValueError,'pending requirements'):self.store.set_gpu_budget(self.sid,32)
        self.assertIsNone(self.store.show(self.sid)['versions'][-1]['contract']['budget'])

    def test_cli_records_initial_cap_without_llm_remote_config_or_submission(self):
        with patch.object(Sessions,'clarify') as clarify, \
                patch('vision_rsi.remote.job_request') as remote,contextlib.redirect_stdout(io.StringIO()):
            main(['budget','--session-id',self.sid,'--sessions',str(self.root/'sessions'),
                  '--config',str(self.root/'missing-config.json'),'--gpu-hours','32'])
        clarify.assert_not_called();remote.assert_not_called()
        result=self.store.show(self.sid)
        self.assertEqual(result['versions'][-1]['contract']['budget'],{'gpu_hours':32})
        self.assertEqual(result['versions'][-1]['contract']['open_questions'],[])
        self.assertEqual(result['status'],'ready_for_harness')

    def test_other_resource_caps_are_preserved(self):
        original=copy.deepcopy(self.contract);original['budget']={'adapter_repair_calls':2}
        self.store.define(self.sid,original)
        result=self.store.set_gpu_budget(self.sid,8)
        self.assertEqual(result['versions'][-1]['contract']['budget'],{'gpu_hours':8,'adapter_repair_calls':2})
