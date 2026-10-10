import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.campaign import advance
from vision_rsi.controller_budget import configured_limit,summary
from vision_rsi.policy_audit import verify_trace


class ControllerBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.session={'session_id':'fixture','task_id':'fixture','versions':[{'contract':{}}]}
        self.config={'remote':{'ssh_host':'fixture','workspace':'/workspace'},'controller':{'tool_attempt_limit':1}}
    def run_controller(self,**kwargs):
        return advance(self.session,self.config,self.root/'campaigns',self.root/'runs',**kwargs)

    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare',return_value={'status':'ready_to_submit','plan_id':'fixture'})
    def test_restarts_and_resume_do_not_refresh_limit(self,prepare,submit):
        state=self.run_controller();self.assertEqual(state['status'],'controller_budget_exhausted')
        self.assertEqual(state['controller_tool_budget']['admitted_attempts'],1)
        self.assertEqual(state['controller_tool_budget']['remaining_attempts'],0)
        before=Path(state['state_path']).read_bytes()
        self.run_controller();self.assertEqual(Path(state['state_path']).read_bytes(),before)
        self.run_controller(control='pause');self.run_controller(control='resume')
        self.assertEqual(self.run_controller()['controller_tool_budget']['remaining_attempts'],0)
        self.assertTrue(verify_trace(state)['verified']);submit.assert_not_called();prepare.assert_called_once()
        changed=copy.deepcopy(self.config);changed['controller']['tool_attempt_limit']=2
        with self.assertRaisesRegex(ValueError,'differs'):
            advance(self.session,changed,self.root/'campaigns',self.root/'runs',selected_campaign=state['campaign_id'])

    @patch('vision_rsi.campaign.submit',side_effect=RuntimeError('uncertain fixture submission'))
    @patch('vision_rsi.campaign.prepare',return_value={'status':'ready_to_submit','plan_id':'fixture'})
    def test_uncertain_attempt_remains_charged_and_intent_is_retained(self,prepare,submit):
        self.config['controller']['tool_attempt_limit']=2
        with self.assertRaises(RuntimeError):self.run_controller()
        state=self.run_controller()
        self.assertEqual(state['status'],'controller_budget_exhausted')
        self.assertEqual(state['controller_tool_budget']['admitted_attempts'],2)
        self.assertEqual(state['intent']['tool_attempts'][-1]['status'],'uncertain')
        submit.assert_called_once()

    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare',return_value={'status':'ready_to_submit','plan_id':'fixture'})
    def test_explicit_retry_consumes_another_attempt(self,prepare,submit):
        self.config['controller']['tool_attempt_limit']=3
        submit.side_effect=[RuntimeError('uncertain fixture'),{'run_id':'fixture','status':'submitted'}]
        with self.assertRaises(RuntimeError):self.run_controller()
        recovered=self.run_controller();self.assertEqual(recovered['controller_tool_budget']['admitted_attempts'],3)
        exhausted=self.run_controller();self.assertEqual(exhausted['status'],'controller_budget_exhausted')
        self.assertIsNone(exhausted['intent']);self.assertEqual(submit.call_count,2)
        self.assertTrue(verify_trace(exhausted)['verified'])

    @patch('vision_rsi.campaign.prepare')
    def test_zero_cap_never_executes_and_invalid_caps_rejected(self,prepare):
        self.config['controller']['tool_attempt_limit']=0
        self.assertEqual(self.run_controller()['status'],'controller_budget_exhausted');prepare.assert_not_called()
        for value in (True,1.0,None,-1,100001,'2'):
            with self.assertRaises(ValueError):configured_limit({'controller':{'tool_attempt_limit':value}})
        self.assertIsNone(configured_limit({}))
        with self.assertRaises(ValueError):configured_limit({'controller':{'unknown_limit':1}})

    @patch('vision_rsi.campaign.prepare',return_value={'status':'ready_to_submit','plan_id':'fixture'})
    def test_missing_accounting_blocks_execution_but_can_be_inspected(self,prepare):
        state=self.run_controller();path=Path(state['state_path']);saved=json.loads(path.read_text())
        saved['history'][0]['tool_attempts']=[];path.write_text(json.dumps(saved));before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'accounting missing'):self.run_controller()
        self.assertEqual(path.read_bytes(),before)
        shown=self.run_controller(control='show');self.assertFalse(shown['controller_tool_budget']['valid'])
        self.assertEqual(path.read_bytes(),before);self.assertTrue(self.run_controller(control='pause')['paused'])
        with self.assertRaises(ValueError):verify_trace(saved)

    def test_compacted_policy_view_does_not_reduce_counted_attempts(self):
        from vision_rsi.strategy_context import history_context
        rows=[{'action':{'id':'observe-'+str(i),'kind':'observe'},'status':'completed','result':{},
               'tool_attempts':[{'status':'completed','elapsed_seconds':0}]} for i in range(1000)]
        state={'binding':{'controller_tool_attempt_limit':1000},'history':rows}
        self.assertLess(len(history_context(rows,4)),1000)
        self.assertEqual(summary(state)['admitted_attempts'],1000)
        self.assertEqual(summary(state)['remaining_attempts'],0)
        state['binding']['controller_tool_attempt_limit']=999
        with self.assertRaisesRegex(ValueError,'exceeds'):summary(state)

    def test_corrupt_accounting_is_not_repaired_into_remaining_budget(self):
        state={'binding':{'controller_tool_attempt_limit':1},'history':[],
               'intent':{'status':'reserved','tool_attempts':[{'status':'started'}]}}
        self.assertEqual(summary(state)['remaining_attempts'],0)
        for attempt in ({'status':'invented'},{'status':'started','elapsed_seconds':True},{'status':'started','elapsed_seconds':float('nan')}):
            changed=copy.deepcopy(state);changed['intent']['tool_attempts']=[attempt]
            with self.assertRaises(ValueError):summary(changed)
        with self.assertRaises(ValueError):summary({'binding':{},'history':[],'controller_budget_exhausted':True})
        with self.assertRaises(ValueError):summary({'binding':{'controller_tool_attempt_limit':None},'history':[]})
