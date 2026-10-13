import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.candidates import git
from vision_rsi.contracts import Sessions
from vision_rsi.harness_progress import advance, status, run_until_blocked
from vision_rsi.runner import atomic_json


def proposal():
    # Protocol fixture only; deliberately not a trained image classifier.
    source='\n'.join('def '+name+'(request):\n    return request["result"]\n'
                     for name in ('load_data','train','predict','evaluate'))
    source+='\ndef smoke(request):\n    return {"stages":["load_data","train","predict","evaluate"],"training_performed":False}\n'
    return {'hypothesis':'Protocol fixture','expected_improvement':'Check orchestration only',
            'evaluation_plan':'No model quality claim',
            'edits':[{'path':'vision_rsi/harness_fixture.py','base_sha256':None,'content':source}]}


class HarnessProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        git(self.repo,'init');(self.repo/'vision_rsi').mkdir()
        (self.repo/'vision_rsi/__init__.py').write_text('')
        (self.repo/'vision_rsi/research.py').write_text('"""Protocol fixture baseline."""\n')
        git(self.repo,'add','.')
        git(self.repo,'-c','user.name=Test','-c','user.email=test@local.invalid','commit','-m','baseline')
        self.store=Sessions(self.root/'sessions')
        created=self.store.create('catdog','猫狗分类')
        self.contract={'goal':'猫狗分类','inputs':{'image':{'type':'image','required':True}},
                       'output_schema':{'type':'object','properties':{
                           'label':{'type':'string','enum':['cat','dog']},
                           'confidence':{'type':'number','minimum':0,'maximum':1}},
                           'required':['label','confidence']},
                       'acceptance':{'metric':'accuracy','threshold':80,'direction':'maximize',
                                     'evaluation_protocol':'Independent heldout classification percent'},
                       'budget':{'gpu_hours':10},'assumptions':[],'open_questions':[],
                       'example_input':{'sample_id':'one','inputs':{'image':{'type':'image','uri':'cat.jpg'}}},
                       'example_output':{'label':'cat','confidence':.9}}
        self.session=self.store.define(created['session_id'],self.contract)
        self.config={'llm':{'model':'fixture','base_url':'https://fixture.invalid'},'remote':{},'research':{}}
        self.output=self.root/'harness'

    @patch('vision_rsi.remote.check_candidate')
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_continue_crosses_default_permission_gate_and_repairs_in_same_call(self,client,remote):
        self.config['research']={'allow_candidate_writes':False,'allow_candidate_checks':False}
        self.assertEqual(self.run_step()['status'],'awaiting_generation')
        client.return_value.complete.side_effect=[{'content':'invalid JSON'}, {'content':json.dumps(proposal())}]
        self.config['remote']={'ssh_host':'fixture','workspace':'/fixture'}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'observation':{'results':[{'stages':['load_data','train','predict','evaluate'],'training_performed':False}]}}
        result=run_until_blocked(self.session,self.config,self.output,self.repo)
        self.assertEqual(result['status'],'backend_protocol_checked')
        self.assertEqual(client.return_value.complete.call_count,2)
        self.assertEqual(remote.call_count,1)
        self.assertFalse(result['training_performed'])
        self.assertEqual(run_until_blocked(self.session,self.config,self.output,self.repo)['status'],'backend_protocol_checked')
        self.assertEqual(client.return_value.complete.call_count,2)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_autonomous_unknown_generation_stops_without_retry(self,client):
        client.return_value.complete.side_effect=RuntimeError('outcome unknown')
        for _ in range(2):
            result=run_until_blocked(self.session,self.config,self.output,self.repo)
            self.assertEqual(result['status'],'generation_uncertain')
        self.assertEqual(client.return_value.complete.call_count,1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_autonomous_repair_cap_survives_repeated_continue(self,client):
        client.return_value.complete.return_value={'content':'invalid JSON'}
        result=run_until_blocked(self.session,self.config,self.output,self.repo)
        self.assertEqual(len(result['attempts']),2)
        self.assertEqual(run_until_blocked(self.session,self.config,self.output,self.repo)['status'],'repair_limit_reached')
        self.assertEqual(client.return_value.complete.call_count,2)

    def run_step(self,**kwargs):
        return advance(self.session,self.config,self.output,self.repo,**kwargs)

    def test_status_does_not_create_files_and_start_checks_real_interface_artifacts(self):
        self.assertEqual(status(self.session,self.output)['status'],'not_started')
        self.assertFalse(self.output.exists())
        with patch('vision_rsi.llm.OpenAICompatibleClient') as client:
            result=self.run_step()
            self.assertEqual(result['status'],'awaiting_generation')
            self.assertEqual(result['interface_check']['status'],'interface_checked')
            self.assertFalse(result['interface_check']['model_available'])
            self.assertTrue((Path(result['interface']['directory'])/'harness.py').is_file())
            again=self.run_step()
            self.assertEqual(result['interface']['bundle_id'],again['interface']['bundle_id'])
            self.assertEqual(again['completed_this_turn'],[])
            client.assert_not_called()
        self.assertEqual(self.store.show(self.session['session_id'])['versions'],self.session['versions'])

    @patch('vision_rsi.remote.check_candidate')
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_generation_real_git_candidate_and_cached_smoke_keep_quality_unverified(self,client,remote):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        result=self.run_step(generate_backend=True)
        self.assertEqual(result['status'],'awaiting_smoke')
        self.assertTrue((Path(result['candidate_source'])/'vision_rsi/harness_fixture.py').is_file())
        self.assertEqual(self.run_step(check_backend=True)['status'],'remote_required')
        remote.assert_not_called()
        self.config['remote']={'ssh_host':'fixture','workspace':'/fixture'}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'observation':{'results':[{'stages':['load_data','train','predict','evaluate'],'training_performed':False}]}}
        result=self.run_step()
        self.assertEqual(result['status'],'backend_protocol_checked')
        self.assertFalse(result['gpu_dispatch_ready']);self.assertFalse(result['quality_verified'])
        self.assertFalse(result['training_performed'])
        self.session=self.store.define(self.session['session_id'],self.contract)
        self.assertEqual(self.run_step()['candidate'],result['candidate'])
        self.assertEqual(client.return_value.complete.call_count,1)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_known_bad_response_gets_one_feedback_bound_repair(self,client):
        client.return_value.complete.side_effect=[{'content':'invalid JSON'}, {'content':json.dumps(proposal())}]
        first=self.run_step(generate_backend=True)
        self.assertEqual(first['status'],'generation_failed')
        second=self.run_step()
        self.assertEqual(second['status'],'awaiting_smoke')
        self.assertEqual(len(second['attempts']),2)
        self.assertNotEqual(second['attempts'][0]['request_id'],second['attempts'][1]['request_id'])
        prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
        self.assertEqual(prompt['previous_attempt_feedback']['previous_response'],'invalid JSON')
        self.run_step()
        self.assertEqual(client.return_value.complete.call_count,2)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_repair_limit_and_unknown_outcome_never_create_endless_requests(self,client):
        client.return_value.complete.return_value={'content':'invalid JSON'}
        self.run_step(generate_backend=True);self.run_step()
        self.assertEqual(self.run_step()['status'],'repair_limit_reached')
        self.assertEqual(client.return_value.complete.call_count,2)
        self.output=self.root/'uncertain'
        client.return_value.complete.side_effect=RuntimeError('Transport outcome unknown')
        self.assertEqual(self.run_step(generate_backend=True)['status'],'generation_uncertain')
        self.assertEqual(self.run_step(generate_backend=True)['status'],'generation_uncertain')
        self.assertEqual(client.return_value.complete.call_count,3)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_known_unsent_requires_explicit_retry_and_retains_original_request(self,client):
        from vision_rsi.llm import LLMNotDispatched
        client.return_value.complete.side_effect=LLMNotDispatched('Local quota denied before dispatch')
        first=self.run_step(generate_backend=True)
        self.assertEqual(first['status'],'generation_not_dispatched')
        self.assertEqual(self.run_step()['status'],'generation_not_dispatched')
        self.assertEqual(client.return_value.complete.call_count,1)
        client.return_value.complete.side_effect=None
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        repaired=self.run_step(generate_backend=True)
        self.assertEqual(repaired['status'],'awaiting_smoke')
        self.assertEqual(repaired['attempts'][0]['status'],'not_dispatched')
        self.assertNotEqual(repaired['attempts'][0]['request_id'],repaired['attempts'][1]['request_id'])

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_crash_after_candidate_receipt_recovers_without_another_api_call(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        def crash(path,value):
            if path.name=='progress.json' and 'candidate' in value:
                raise OSError('Simulated interruption after durable generation receipt')
            return atomic_json(path,value)
        with patch('vision_rsi.harness_progress.atomic_json',side_effect=crash):
            with self.assertRaises(OSError):self.run_step(generate_backend=True)
        recovered=self.run_step()
        self.assertEqual(recovered['status'],'awaiting_smoke')
        self.assertEqual(client.return_value.complete.call_count,1)
        self.assertTrue(any('恢复' in item for item in recovered['completed_this_turn']))

    @patch('vision_rsi.remote.check_candidate')
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_uncertain_smoke_is_not_repeated(self,client,remote):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        self.config['remote']={'ssh_host':'fixture','workspace':'/fixture'}
        remote.side_effect=RuntimeError('Unknown remote outcome')
        result=self.run_step(generate_backend=True,check_backend=True)
        self.assertEqual(result['status'],'smoke_uncertain')
        self.assertEqual(self.run_step(check_backend=True)['status'],'smoke_uncertain')
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_failed_smoke_repairs_once_using_saved_test_evidence(self,client,remote):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        self.config['remote']={'ssh_host':'fixture','workspace':'/fixture'}
        def check(endpoint,request):
            rows=[] if remote.call_count==1 else [{'stages':['load_data','train','predict','evaluate'],'training_performed':False}]
            return {'status':'executed_unverified','source_hashes':request['source_hashes'],'observation':{'results':rows}}
        remote.side_effect=check
        first=self.run_step(generate_backend=True,check_backend=True)
        self.assertEqual(first['status'],'smoke_failed')
        second=self.run_step()
        self.assertEqual(second['status'],'backend_protocol_checked')
        self.assertNotEqual(first['candidate']['candidate_id'],second['candidate']['candidate_id'])
        prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
        self.assertEqual(prompt['previous_attempt_feedback']['failure']['status'],'backend_protocol_smoke_failed')
        self.assertEqual(remote.call_count,2)
        self.assertEqual(client.return_value.complete.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_crash_after_remote_receipt_recovers_cached_check(self,client,remote):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        self.config['remote']={'ssh_host':'fixture','workspace':'/fixture'}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'observation':{'results':[{'stages':['load_data','train','predict','evaluate'],'training_performed':False}]}}
        def crash(path,value):
            if path.name=='progress.json' and 'smoke' in value:raise OSError('Interrupted after remote receipt')
            return atomic_json(path,value)
        with patch('vision_rsi.harness_progress.atomic_json',side_effect=crash):
            with self.assertRaises(OSError):self.run_step(generate_backend=True,check_backend=True)
        result=self.run_step()
        self.assertEqual(result['status'],'backend_protocol_checked')
        self.assertEqual(remote.call_count,1)
        self.assertEqual(client.return_value.complete.call_count,1)

    def test_pending_requirements_block_before_artifact_or_api_work(self):
        self.session['pending_request']=True
        with self.assertRaises(ValueError):self.run_step(generate_backend=True)
        self.assertFalse(self.output.exists())
        self.session.pop('pending_request')
        self.session['versions'][-1]['review_required']=[{'path':'goal'}]
        with self.assertRaises(ValueError):self.run_step(generate_backend=True)
        self.assertFalse(self.output.exists())

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_tampered_source_is_not_used_or_silently_regenerated(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        result=self.run_step(generate_backend=True)
        source=Path(result['candidate_source'])/'vision_rsi/harness_fixture.py'
        source.write_text('changed source')
        with self.assertRaises(ValueError):self.run_step()
        self.assertEqual(client.return_value.complete.call_count,1)
