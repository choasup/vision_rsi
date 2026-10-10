import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.campaign import advance,choose,lease,list_campaigns


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.session={'session_id':'test-session','task_id':'test','versions':[{'contract':{'goal':'detect','acceptance':{'threshold':60}}}]}
        self.config={'remote':{'ssh_host':'fixture','workspace':'/workspace'}}
        self.plan={'status':'ready_to_submit','plan_id':'p','blockers':[]}
        self.record={'run_id':'train-one','status':'submitted','actual_gpu_hours':None,'details':{}}
    def advance(self,**kwargs):
        return advance(self.session,self.config,self.root/'campaigns',self.root/'runs',**kwargs)

    def test_analysis_budget_snapshot_includes_other_failed_session_runs(self):
        from vision_rsi.campaign import execute
        from vision_rsi.training_runs import TrainingRuns
        session=dict(self.session,versions=[{'contract':{'budget':{'gpu_hours':1}}}])
        runs=TrainingRuns(self.root/'actual-ledger')
        try:
            plan={'status':'ready_to_submit','plan_id':'a'*64,'plan_path':str(self.root/'plan.json'),
                  'session_id':session['session_id'],'contract':session['versions'][0]['contract'],
                  'scheduler':{'gpu_devices':[0],'timeout_seconds':355}}
            first,_=runs.reserve(plan,self.config['remote'])
            details=dict(first['details'],acceptance_review={'passed':False,'box_AP':40,'threshold':60})
            runs.update(first['run_id'],'completed',details,actual=.2)
            other,_=runs.reserve(dict(plan,plan_id='b'*64),self.config['remote'])
            runs.update(other['run_id'],'failed',other['details'],actual=.3)
            result=execute({'kind':'analyze'},{'run_id':first['run_id']},session,self.config,self.root,runs)
            self.assertEqual(result['actual_gpu_hours'],.2)
            self.assertEqual(result['authorized_gpu_hours'],1)
            self.assertAlmostEqual(result['remaining_gpu_hours'],.5)
            self.assertEqual(len(runs.list(session['session_id'])),2)
        finally:runs.close()

    @patch('vision_rsi.campaign.prepare')
    def test_selected_campaign_rejects_ledger_changes_on_resume_and_advance(self,prepare):
        prepare.return_value={'status':'blocked','blockers':['fixture']}
        original={'model':'fixture','base_url':'https://fixture.invalid',
                  'usage_ledger':str(self.root/'usage.sqlite3'),'usage_call_limit':2,'thinking':'disabled'}
        self.config['llm']=original.copy()
        state=self.advance(research_rounds=1);cid=state['campaign_id']
        for changed in (dict(original,usage_ledger=str(self.root/'different.sqlite3')),
                        dict(original,usage_call_limit=3),
                        {k:v for k,v in original.items() if k!='usage_ledger'},
                        dict(original,thinking='enabled')):
            self.config['llm']=changed
            self.assertEqual(self.advance(control='show',selected_campaign=cid)['campaign_id'],cid)
            self.assertTrue(self.advance(control='pause',selected_campaign=cid)['paused'])
            for kwargs in ({'control':'resume'},{}):
                with self.assertRaisesRegex(ValueError,'differs from selected campaign'):
                    self.advance(selected_campaign=cid,**kwargs)
        self.config['llm']=original
        self.assertFalse(self.advance(control='resume',selected_campaign=cid)['paused'])

    @patch('vision_rsi.campaign.execute')
    @patch('vision_rsi.campaign.available')
    def test_known_unsent_pauses_until_explicit_resume(self,available,execute):
        from vision_rsi.llm import LLMNotDispatched
        available.return_value=[{'id':'proposal-0','kind':'propose_experiment','estimated_cost':1,'expected_gain':0,'uncertainty':1}]
        execute.side_effect=LLMNotDispatched('local admission refused')
        with self.assertRaises(LLMNotDispatched):self.advance(steps=1)
        paused=self.advance(steps=1)
        self.assertEqual(paused['status'],'action_not_dispatched')
        self.assertTrue(paused['paused']);self.assertEqual(execute.call_count,1)
        self.assertEqual(paused['intent']['tool_attempts'][0]['status'],'not_dispatched')
        resumed=self.advance(control='resume')
        self.assertEqual(resumed['intent']['explicit_retry'],1)
        self.assertFalse(resumed['paused'])
        with self.assertRaises(LLMNotDispatched):self.advance(steps=1)
        self.assertEqual(execute.call_count,2)

    @patch('vision_rsi.campaign.choose')
    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare')
    def test_policy_stop_is_persisted_and_does_not_restart_on_next_advance(self,prepare,submit,choose):
        prepare.return_value=self.plan
        choose.side_effect=[({'action_id':'prepare-0','rationale':'prepare'},'first-report'),
                            ({'action_id':None,'rationale':'Stop this research attempt'},'stop-report')]
        policy={'store':'fixture','candidate_id':'fixture','module':'fixture'}
        first=self.advance(policy=policy)
        self.assertEqual(first['status'],'policy_stopped');self.assertEqual(len(first['history']),1)
        self.assertEqual(first['policy_stop']['policy_evidence'],'stop-report')
        self.assertGreaterEqual(first['policy_stop']['policy_elapsed_seconds'],0)
        second=self.advance(policy=policy)
        self.assertEqual(second['policy_stop'],first['policy_stop'])
        self.assertEqual(choose.call_count,2);submit.assert_not_called()

    @patch('vision_rsi.campaign.TrainingRuns')
    @patch('vision_rsi.campaign.collect')
    @patch('vision_rsi.campaign.observe')
    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare')
    def test_training_lifecycle_reuses_state_and_analyzes_without_registration(self,prepare,submit,observe,collect,runs):
        prepare.return_value=self.plan;submit.return_value=self.record;runs.return_value.list.return_value=[]
        first=self.advance();self.assertEqual(first['status'],'waiting')
        self.assertEqual([x['action']['kind'] for x in first['history']],['prepare','submit'])
        done=dict(self.record,status='completed',actual_gpu_hours=1,details={'acceptance_review':{'passed':False,'box_AP':42,'threshold':60}})
        observe.return_value=done;collect.return_value=done;runs.return_value.get.return_value=done
        second=self.advance()
        self.assertEqual(second['status'],'needs_research');self.assertEqual(second['analysis']['metric_gap'],18)
        self.assertFalse(second['policy_adopted']);self.assertFalse(second['analysis']['method_or_agent_improvement_verified'])
        self.advance();submit.assert_called_once();prepare.assert_called_once();collect.assert_called_once()

    @patch('vision_rsi.campaign.TrainingRuns')
    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare')
    def test_interrupted_submit_keeps_intent_and_frozen_plan(self,prepare,submit,runs):
        prepare.return_value=self.plan;runs.return_value.list.return_value=[]
        submit.side_effect=[RuntimeError('response lost'),self.record]
        with self.assertRaises(RuntimeError):self.advance()
        path=next((self.root/'campaigns').glob('*/*/state.json'))
        pending=json.loads(path.read_text());self.assertEqual(pending['intent']['action']['id'],'submit-1')
        resumed=self.advance();self.assertEqual(resumed['history'][-1]['action']['id'],'submit-1')
        self.assertIsNone(resumed['intent']);self.assertEqual(submit.call_args_list[0].args[0],submit.call_args_list[1].args[0])
        attempts=resumed['history'][-1]['tool_attempts']
        self.assertEqual([attempt['status'] for attempt in attempts],['uncertain','completed'])
        self.assertTrue(all(attempt['elapsed_seconds']>=0 for attempt in attempts))

    @patch('vision_rsi.campaign.prepare')
    @patch('vision_rsi.campaign.submit')
    def test_pending_action_cannot_resume_with_changed_control_source(self,submit,prepare):
        prepare.return_value=self.plan;submit.side_effect=RuntimeError('uncertain submission')
        with self.assertRaises(RuntimeError):self.advance()
        path=next((self.root/'campaigns').glob('*/*/state.json'));state=json.loads(path.read_text())
        state['intent']['control_sources']['campaign.py']='0'*64;path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'frozen source'):self.advance()
        submit.assert_called_once()

    @patch('vision_rsi.campaign.prepare')
    def test_blocked_no_repeated_preflight_and_pause(self,prepare):
        prepare.return_value={'status':'blocked','blockers':['Need real GPU budget']}
        result=self.advance();self.assertEqual(result['status'],'blocked')
        self.advance();prepare.assert_called_once()
        self.advance(control='pause');self.assertTrue(self.advance()['paused'])
        self.assertFalse(self.advance(control='resume')['paused'])

    @patch('vision_rsi.candidates.Candidates')
    def test_policy_receives_actual_observations_and_can_direct_research(self,candidates):
        brief='Test a new method using the measured gap, without changing requirements.'
        candidates.return_value.check_strategy.return_value={'status':'protocol_passed','protocol_report_path':'fixture',
            'response':{'observation':{'results':[{'action_id':'research-1','rationale':'measured failure','research_brief':brief}]}}}
        state={'history':[{'action':{'id':'analyze-0','kind':'analyze'},'status':'completed','result':{'metric_gap':18,'acceptance_review':{'box_AP':42,'threshold':60}}}]}
        actions=[{'id':'research-1','kind':'propose_experiment','estimated_cost':1,'expected_gain':2,'uncertainty':.1}]
        decision,_=choose(state,actions,1,{'store':'fixture','candidate_id':'fixture','module':'fixture'},self.config['remote'])
        context=candidates.return_value.check_strategy.call_args.args[3][0]
        self.assertEqual(context['history'][0]['observation']['measurement']['value'],42)
        self.assertEqual(decision['research_brief'],brief)

    @patch('vision_rsi.experiments.propose_next')
    def test_execute_passes_selected_research_brief_to_method_planner(self,planner):
        from unittest.mock import MagicMock
        from vision_rsi.campaign import execute
        runs=MagicMock();runs.get.return_value=self.record
        state={'run_id':self.record['run_id'],'campaign_id':'a'*64,'intent':{'decision':{'research_brief':'A bounded hypothesis'}}}
        execute({'kind':'propose_experiment'},state,self.session,{**self.config,'llm':{}},self.root,runs)
        self.assertEqual(planner.call_args.kwargs['research_brief'],'A bounded hypothesis')

    @patch('vision_rsi.candidates.Candidates')
    def test_experimental_strategy_cannot_invent_tool(self,candidates):
        candidates.return_value.check_strategy.return_value={'status':'protocol_passed','protocol_report_path':'fixture',
            'response':{'observation':{'results':[{'action_id':'arbitrary-shell','rationale':'wrong'}]}}}
        with self.assertRaisesRegex(ValueError,'unavailable'):
            choose({'history':[]},[{'id':'prepare-0','kind':'prepare','estimated_cost':1,'expected_gain':2,'uncertainty':0}],1,
                   {'store':'fixture','candidate_id':'fixture','module':'fixture'},self.config['remote'])

    def test_os_lease_releases_after_exception(self):
        path=self.root/'lease'
        with self.assertRaises(RuntimeError):
            with lease(path):raise RuntimeError('simulated crash')
        with lease(path):pass

    @patch('vision_rsi.campaign.prepare')
    def test_campaign_id_restores_research_settings_and_rejects_changed_execution(self,prepare):
        prepare.return_value={'status':'blocked','blockers':['missing data']}
        state=self.advance(research_rounds=2)
        cid=state['campaign_id']
        shown=self.advance(control='show',selected_campaign=cid)
        self.assertEqual(shown['research_rounds'],2)
        self.assertEqual(shown['campaign_id'],cid)
        rows=list_campaigns(self.session['session_id'],self.root/'campaigns')
        self.assertEqual(rows[0]['campaign_id'],cid);self.assertFalse(rows[0]['live_remote_poll'])
        self.assertTrue(self.advance(control='pause',selected_campaign=cid)['paused'])
        with self.assertRaisesRegex(ValueError,'cannot be overridden'):
            self.advance(control='show',selected_campaign=cid,research_rounds=0)
        self.session['versions'][-1]['contract']['acceptance']['threshold']=65
        self.assertEqual(self.advance(control='show',selected_campaign=cid)['binding']['contract']['acceptance']['threshold'],60)
        with self.assertRaisesRegex(ValueError,'differs from selected campaign'):
            self.advance(selected_campaign=cid)

    @patch('vision_rsi.experiments.propose_next')
    @patch('vision_rsi.campaign.TrainingRuns')
    @patch('vision_rsi.campaign.collect')
    @patch('vision_rsi.campaign.observe')
    @patch('vision_rsi.campaign.submit')
    @patch('vision_rsi.campaign.prepare')
    def test_bounded_research_round_moves_to_new_plan_without_changing_contract(self,prepare,submit,observe,collect,runs,propose):
        self.config['llm']={'model':'fixture','base_url':'https://fixture.invalid'}
        prepare.return_value=self.plan;runs.return_value.list.return_value=[]
        next_record=dict(self.record,run_id='train-two')
        submit.side_effect=[self.record,next_record]
        self.advance(research_rounds=1)
        done=dict(self.record,status='completed',actual_gpu_hours=.01,details={'acceptance_review':{'passed':False,'box_AP':42,'threshold':60}})
        observe.return_value=done;collect.return_value=done;runs.return_value.get.return_value=done
        self.advance(research_rounds=1)
        propose.return_value=dict(self.plan,plan_id='p2')
        result=self.advance(research_rounds=1)
        self.assertEqual(result['run_id'],'train-two');self.assertEqual(result['proposals_attempted'],1)
        self.assertEqual(result['plan']['plan_id'],'p2');self.assertFalse(result['policy_adopted'])
        propose.assert_called_once()
