import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.campaign import advance,choose,lease


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

    @patch('vision_rsi.campaign.prepare')
    def test_blocked_no_repeated_preflight_and_pause(self,prepare):
        prepare.return_value={'status':'blocked','blockers':['Need real GPU budget']}
        result=self.advance();self.assertEqual(result['status'],'blocked')
        self.advance();prepare.assert_called_once()
        self.advance(control='pause');self.assertTrue(self.advance()['paused'])
        self.assertFalse(self.advance(control='resume')['paused'])

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
