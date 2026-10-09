import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.candidates import Candidates,git,validate_proposal


def proposal():
    return {'hypothesis':'Select experiments by gain per remaining cost','expected_improvement':'Higher held-out utility within equal budgets',
            'evaluation_plan':'Paired seeds, same budgets and frozen target; reject regressions',
            'edits':[{'path':'vision_rsi/strategy_candidate.py','base_sha256':None,
                      'content':'def choose(rows):\n    return max(rows, key=lambda row: row["utility"] / row["cost"])\n'}]}


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.repo=root/'source';self.repo.mkdir()
        git(self.repo,'init');(self.repo/'vision_rsi').mkdir()
        (self.repo/'vision_rsi/research.py').write_text('BASELINE = True\n')
        (self.repo/'vision_rsi/controller.py').write_text('CONTROLLER = True\n')
        git(self.repo,'add','.');git(self.repo,'-c','user.name=Test','-c','user.email=test@local.invalid','commit','-m','baseline')
        self.store=Candidates(root/'candidates',self.repo);self.addCleanup(self.store.close)

    def test_git_isolation_idempotence_and_tamper(self):
        original=git(self.repo,'rev-parse','HEAD')
        record=self.store.create(proposal(),{'task':'test'})
        self.assertEqual(record['status'],'awaiting_runtime_evaluation')
        self.assertFalse(record['adopted']);self.assertFalse(record['runtime_verified'])
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),original)
        self.assertFalse((self.repo/'vision_rsi/strategy_candidate.py').exists())
        self.assertEqual(self.store.create(proposal(),{'task':'test'}),record)
        (Path(record['checkout'])/'vision_rsi/strategy_candidate.py').write_text('changed = True')
        with self.assertRaisesRegex(ValueError,'Git state changed'):self.store.verify(record)

    def test_protected_paths_invalid_code_and_base_hash(self):
        for name in ('vision_rsi/acceptance.py','vision_rsi/contracts.py','vision_rsi/jobs.py','../escape.py','vision_rsi/strategy_X.py'):
            changed=proposal();changed['edits'][0]['path']=name
            with self.subTest(name=name),self.assertRaises(ValueError):validate_proposal(changed)
        changed=proposal();changed['edits'][0]['content']='def broken('
        with self.assertRaises(SyntaxError):validate_proposal(changed)
        changed=proposal();changed['edits'][0].update(path='vision_rsi/research.py',base_sha256=None)
        with self.assertRaisesRegex(ValueError,'Base source hash'):self.store.create(changed,{})

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_actual_response_record_reused_without_api_retry(self,client):
        client.return_value.complete.return_value={'model':'fixture','content':json.dumps(proposal()),'usage':{'total_tokens':20}}
        config={'model':'fixture','base_url':'https://fixture.invalid','api_key_env':'UNUSED'}
        first=self.store.propose('request-1',{'threshold':60},{'observed':True},config)
        self.assertEqual(first,self.store.propose('request-1',{'threshold':60},{'observed':True},config))
        client.return_value.complete.assert_called_once()
        with self.assertRaisesRegex(ValueError,'different research context'):
            self.store.propose('request-1',{'threshold':59},{'observed':True},config)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_timeout_is_not_automatically_retried(self,client):
        client.return_value.complete.side_effect=TimeoutError('simulated uncertain response')
        config={'model':'fixture','base_url':'https://fixture.invalid'}
        with self.assertRaises(TimeoutError):self.store.propose('request-2',{},[],config)
        with self.assertRaisesRegex(RuntimeError,'Uncertain API request'):self.store.propose('request-2',{},[],config)
        client.return_value.complete.assert_called_once()

    def test_dirty_main_source_refused(self):
        (self.repo/'vision_rsi/research.py').write_text('changed = True')
        with self.assertRaisesRegex(ValueError,'Commit tracked'):self.store.create(proposal(),{})

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_empty_flash_response_is_saved_without_retry(self,client):
        client.return_value.complete.return_value={'model':'deepseek-flash','content':'','usage':{'completion_tokens':6000}}
        config={'model':'deepseek-flash','base_url':'https://fixture.invalid'}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'no proposal text'):self.store.propose('flash-empty',{},[],config)
        client.return_value.complete.assert_called_once()
        self.assertEqual(client.call_args.args[0]['thinking'],'disabled')

    @patch('vision_rsi.remote.check_candidate')
    def test_runtime_check_preserves_untrusted_observation_without_adoption(self,remote):
        record=self.store.create(proposal(),{'task':'test'})
        def response(endpoint,request):
            return {'status':'executed_unverified','source_hashes':request['source_hashes'],
                    'observation':{'results':[{'adopt_rule_met':True}]},'adopted':False}
        remote.side_effect=response
        result=self.store.check(record['candidate_id'],{'workspace':'/workspace'},'vision_rsi.strategy_candidate','choose',[{'rows':[]}])
        self.assertFalse(result['adopted']);self.assertTrue(Path(result['report_path']).is_file())
        self.assertFalse(self.store.verify(record)['runtime_verified'])
        remote.return_value={'status':'executed_unverified','source_hashes':{}}
        remote.side_effect=None
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            self.store.check(record['candidate_id'],{'workspace':'/workspace'},'vision_rsi.strategy_candidate','choose',[{}])

    @patch('vision_rsi.remote.check_candidate')
    def test_strategy_protocol_rejects_completed_action_despite_self_claim(self,remote):
        record=self.store.create(proposal(),{})
        def response(endpoint,request):
            return {'status':'executed_unverified','source_hashes':request['source_hashes'],
                    'observation':{'results':[{'action_id':'old','rationale':'I claim success','adopt_rule_met':True}]},'adopted':False}
        remote.side_effect=response
        cases=[{'history':[{'id':'old','status':'completed'}],
                'actions':[{'id':'old','estimated_cost':1,'expected_gain':2,'uncertainty':0}],'budget':2}]
        result=self.store.check_strategy(record['candidate_id'],{'workspace':'/workspace'},'vision_rsi.strategy_candidate',cases)
        self.assertEqual(result['status'],'protocol_failed');self.assertFalse(result['adopted'])
        self.assertIn('already attempted',result['protocol_failures'][0]['error'])
