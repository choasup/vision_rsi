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
    def failed_adapter(self,remote,call_limit=20):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        contract['budget'].pop('llm_calls',None)
        contract['budget']['adapter_repair_calls']=call_limit
        changed=proposal();changed['edits'][0].update(path='vision_rsi/adapter_fixture.py',content='def predict(sample):\n    start=-1 if sample["sample_id"].endswith("-invalid") else 0\n    return {"defects": [{"label":"fixture", "start_seconds":start}]}\n')
        parent=self.store.create(changed,{'fixture':True})
        remote.side_effect=lambda endpoint,request: {'status':'executed_unverified','source_hashes':request['source_hashes'],
                    'observation':{'results':[{'defects':[{'label':'fixture','start_seconds':-1 if request['module']=='vision_rsi.adapter_fixture' and case['sample']['sample_id'].endswith('-invalid') else 0}]} for case in request['cases']]}}
        samples=[dict(contract['example_input'],sample_id='development-valid'),dict(contract['example_input'],sample_id='development-invalid')]
        return self.store.check_adapter(parent['candidate_id'],{},'vision_rsi.adapter_fixture','predict',contract,samples)

    @patch('vision_rsi.remote.check_candidate')
    def test_actual_project_cap_denial_does_not_spend_repair_budget(self,remote):
        from vision_rsi.adapter_repair import repair
        from vision_rsi.repair_budget import reconcile
        from vision_rsi.llm import LLMNotDispatched
        failed=self.failed_adapter(remote,call_limit=1)
        ledger=Path(self.temp.name)/'project.sqlite3'
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid',
                 'api_key_env':'VISION_RSI_TEST_KEY','usage_ledger':str(ledger),'usage_call_limit':0}}
        with patch.dict('os.environ',{'VISION_RSI_TEST_KEY':'fixture-only'}),patch('vision_rsi.llm.urlopen') as http:
            with self.assertRaises(LLMNotDispatched):
                repair(self.store,'cap-zero-repair',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
            http.assert_not_called()
        budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
        self.assertEqual(budget['remaining_calls'],1)
        self.assertEqual(budget['not_dispatched_calls'],1)
        self.assertEqual(self.store.db.execute('SELECT state FROM requests WHERE id=?',('cap-zero-repair',)).fetchone()[0],'not_dispatched')

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_candidate_known_unsent_requires_new_id(self,client):
        from vision_rsi.llm import LLMNotDispatched
        client.return_value.complete.side_effect=LLMNotDispatched('local admission refused')
        config={'model':'fixture','base_url':'https://fixture.invalid'}
        for _ in range(2):
            with self.assertRaises(LLMNotDispatched):self.store.propose('unsent-candidate',{},[],config)
        self.assertEqual(client.return_value.complete.call_count,1)
        client.return_value.complete.side_effect=None
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        result=self.store.propose('explicit-new-candidate',{},[],config)
        self.assertFalse(result.get('adopted',False))
        self.assertEqual(client.return_value.complete.call_count,2)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_repair_unsent_preserves_history_without_consuming_lineage_call(self,remote,client):
        from vision_rsi.adapter_repair import repair
        from vision_rsi.repair_budget import reconcile
        from vision_rsi.llm import LLMNotDispatched
        failed=self.failed_adapter(remote,call_limit=1)
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid'}}
        client.return_value.complete.side_effect=LLMNotDispatched('local cap exhausted')
        for _ in range(2):
            with self.assertRaises(LLMNotDispatched):
                repair(self.store,'unsent-repair',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        self.assertEqual(client.return_value.complete.call_count,1)
        for rebuild in (False,True):
            if rebuild:
                with self.store.db:
                    self.store.db.execute('DROP TABLE repair_calls');self.store.db.execute('DROP TABLE repair_budgets')
            budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
            self.assertEqual(budget['occupied_calls'],0)
            self.assertEqual(budget['not_dispatched_calls'],1)
            self.assertEqual(budget['unsettled_calls'],0)
            self.assertEqual(budget['remaining_calls'],1)
        client.return_value.complete.side_effect=TimeoutError('actual outcome unknown')
        with self.assertRaises(TimeoutError):
            repair(self.store,'explicit-new-repair',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
        self.assertEqual(budget['occupied_calls'],1);self.assertEqual(budget['remaining_calls'],0)
        self.assertEqual(budget['unsettled_calls'],1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_adapter_repair_retains_lineage_and_replays_without_api_or_runtime(self,remote,client):
        from vision_rsi.adapter_repair import repair
        failed=self.failed_adapter(remote,call_limit=1)
        def respond(messages,**kwargs):
            prompt=json.loads(messages[-1]['content'])
            value={'hypothesis':'Repair invalid temporal bound','expected_improvement':'Development schema conformity',
                   'evaluation_plan':'Same development cases only; not quality or adoption',
                   'edits':[{'path':prompt['required_module'].replace('.','/')+'.py','base_sha256':None,
                             'content':'def predict(sample):\n    return {"defects": [{"label":"fixture", "start_seconds":max(0,-1)}]}\n'}]}
            return {'model':'fixture','content':json.dumps(value),'usage':{'total_tokens':100}}
        client.return_value.complete.side_effect=respond
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid'}}
        result=repair(self.store,'repair-one',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        again=repair(self.store,'repair-one',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        self.assertEqual(result['candidate_id'],again['candidate_id']);self.assertEqual(result['status'],'adapter_contract_passed')
        self.assertEqual(result['parent_candidate_id'],failed['candidate_id']);self.assertFalse(result['quality_verified']);self.assertFalse(result['adopted'])
        self.assertEqual(result['valid_parent_outputs_checked'],1);self.assertEqual(result['behavior_regressions'],[])
        client.return_value.complete.assert_called_once();self.assertEqual(remote.call_count,2)
        from vision_rsi.repair_budget import reconcile
        self.assertEqual(result['repair_budget']['remaining_calls'],0)
        with self.store.db:
            self.store.db.execute('DROP TABLE repair_calls');self.store.db.execute('DROP TABLE repair_budgets')
        budget=reconcile(self.store,result['candidate_id'],failed['contract'])
        self.assertEqual(budget['root_candidate_id'],failed['candidate_id'])
        self.assertEqual(budget['occupied_calls'],1);self.assertEqual(budget['remaining_calls'],0)
        client.return_value.complete.assert_called_once();self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_repair_budget_retains_unknown_calls_and_refuses_new_id_or_increase(self,remote,client):
        from vision_rsi.adapter_repair import repair
        from vision_rsi.repair_budget import reconcile
        failed=self.failed_adapter(remote,call_limit=1)
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid'}}
        client.return_value.complete.side_effect=TimeoutError('API result unknown')
        with self.assertRaises(TimeoutError):repair(self.store,'quota-first',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        with self.assertRaisesRegex(ValueError,'budget exhausted'):repair(self.store,'quota-second',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
        self.assertEqual(budget['unsettled_calls'],1);self.assertEqual(budget['remaining_calls'],0)
        changed=json.loads(json.dumps(failed['contract']));changed['budget']['adapter_repair_calls']=2
        with self.assertRaisesRegex(ValueError,'no implicit reset'):reconcile(self.store,failed['candidate_id'],changed)
        client.return_value.complete.assert_called_once()
        self.assertIsNone(self.store.db.execute('SELECT id FROM requests WHERE id=?',('quota-second',)).fetchone())

    @patch('vision_rsi.remote.check_candidate')
    def test_global_llm_limit_is_not_reinterpreted_as_fresh_repair_quota(self,remote):
        from vision_rsi.repair_budget import reconcile,admit_contract
        failed=self.failed_adapter(remote)
        global_contract=json.loads(json.dumps(failed['contract']));global_contract['budget']['llm_calls']=20
        with self.assertRaisesRegex(ValueError,'Global LLM call budget'):admit_contract(global_contract)
        legacy=json.loads(json.dumps(global_contract));legacy['budget'].pop('adapter_repair_calls')
        budget=reconcile(self.store,failed['candidate_id'],legacy)
        self.assertFalse(budget['new_calls_authorized']);self.assertFalse(budget['global_llm_budget_verified'])
        with self.assertRaisesRegex(ValueError,'audit-only'):admit_contract(legacy)

    @patch.dict('os.environ',{'MISSING_REPAIR_TEST_KEY':''})
    @patch('vision_rsi.llm.urlopen')
    @patch('vision_rsi.remote.check_candidate')
    def test_missing_key_does_not_consume_repair_call_reservation(self,remote,opened):
        from vision_rsi.adapter_repair import repair
        from vision_rsi.repair_budget import reconcile
        failed=self.failed_adapter(remote,call_limit=1)
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid','api_key_env':'MISSING_REPAIR_TEST_KEY'}}
        with self.assertRaisesRegex(ValueError,'API key'):repair(self.store,'missing-local-key',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        self.assertIsNone(self.store.db.execute('SELECT id FROM requests WHERE id=?',('missing-local-key',)).fetchone())
        budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
        self.assertEqual(budget['occupied_calls'],0);self.assertEqual(budget['remaining_calls'],1)
        opened.assert_not_called()

    @patch('vision_rsi.remote.check_candidate')
    def test_repair_budget_concurrent_reservations_admit_only_one_call(self,remote):
        from concurrent.futures import ThreadPoolExecutor
        from vision_rsi.repair_budget import reconcile
        from vision_rsi.runner import digest
        failed=self.failed_adapter(remote,call_limit=1)
        original=json.loads(Path(failed['adapter_report_path']).read_text())
        identity={'kind':'adapter_contract_repair_v1','parent_candidate_id':failed['candidate_id'],
                  'parent_report_sha256':digest(original),'module':'vision_rsi.adapter_fixture','function':'predict'}
        def reserve(request_id):
            store=Candidates(self.store.root,self.repo)
            try:
                try:reconcile(store,failed['candidate_id'],failed['contract'],request_id,identity);return 'admitted'
                except ValueError as error:
                    if 'budget exhausted' not in str(error):raise
                    return 'exhausted'
            finally:store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,['concurrent-a','concurrent-b']))
        self.assertCountEqual(results,['admitted','exhausted'])
        budget=reconcile(self.store,failed['candidate_id'],failed['contract'])
        self.assertEqual(budget['occupied_calls'],1);self.assertEqual(budget['unsettled_calls'],1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_adapter_repair_refuses_changed_feedback_and_uncertain_api(self,remote,client):
        from vision_rsi.adapter_repair import repair
        failed=self.failed_adapter(remote)
        config={'remote':{},'llm':{'model':'fixture','base_url':'https://fixture.invalid'}}
        client.return_value.complete.side_effect=TimeoutError('API response lost')
        with self.assertRaises(TimeoutError):repair(self.store,'repair-lost',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        with self.assertRaisesRegex(RuntimeError,'Uncertain repair API'):repair(self.store,'repair-lost',failed['adapter_report_path'],'vision_rsi.adapter_fixture','predict',config)
        client.return_value.complete.assert_called_once()
        path=Path(failed['adapter_report_path']);changed=json.loads(path.read_text());changed['development_samples'][0]['sample_id']='tampered'
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'original runtime request'):repair(self.store,'repair-tampered',path,'vision_rsi.adapter_fixture','predict',config)
        client.return_value.complete.assert_called_once()

    @patch('vision_rsi.remote.check_candidate')
    def test_stable_candidate_check_does_not_retry_unknown_remote_execution(self,remote):
        record=self.store.create(proposal(),{})
        remote.side_effect=TimeoutError('SSH response lost')
        for index in range(2):
            expected=TimeoutError if index==0 else RuntimeError
            with self.assertRaises(expected):self.store.check(record['candidate_id'],{},'vision_rsi.strategy_candidate','choose',[{'rows':[]}],check_id='a'*32)
        remote.assert_called_once()

    def test_schema_valid_empty_repair_is_not_allowed_to_drop_valid_parent_outputs(self):
        from vision_rsi.adapter_repair import preserved_outputs
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        before={'observation':{'results':[{'defects':[{'label':'fixture','start_seconds':0}]},{'defects':[{'label':'fixture','start_seconds':-1}]}]}}
        after={'observation':{'results':[{'defects':[]},{'defects':[]}]}}
        count,failures=preserved_outputs(contract,before,after)
        self.assertEqual(count,1);self.assertEqual(failures[0]['sample_index'],0)

    @patch('vision_rsi.remote.check_candidate')
    def test_adapter_gate_checks_each_output_without_accepting_quality_claims(self,remote):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        changed=proposal();changed['edits'][0].update(path='vision_rsi/adapter_fixture.py',content='def predict(sample):\n    return {"defects": []}\n')
        record=self.store.create(changed,{'fixture':True})
        def response(values):
            remote.side_effect=lambda endpoint,request: {'status':'executed_unverified','source_hashes':request['source_hashes'],
                    'observation':{'results':values},'adopted':True,'quality_verified':True}
        samples=[contract['example_input'],dict(contract['example_input'],sample_id='another')]
        response([{'defects':[]},{'defects':[]}])
        result=self.store.check_adapter(record['candidate_id'],{},'vision_rsi.adapter_fixture','predict',contract,samples)
        self.assertEqual(result['status'],'adapter_contract_passed')
        self.assertFalse(result['adopted']);self.assertFalse(result['quality_verified']);self.assertFalse(result['acceptance_evaluated'])
        self.assertTrue(Path(result['adapter_report_path']).is_file())
        response([{'defects':[]},{'defects':[{'label':'defect','start_seconds':-1}]}])
        result=self.store.check_adapter(record['candidate_id'],{},'vision_rsi.adapter_fixture','predict',contract,samples)
        self.assertEqual(result['status'],'adapter_contract_failed');self.assertEqual(result['contract_failures'][0]['sample_index'],1)
        response([])
        result=self.store.check_adapter(record['candidate_id'],{},'vision_rsi.adapter_fixture','predict',contract,samples)
        self.assertIn('count',result['contract_failures'][0]['error'])

    @patch('vision_rsi.remote.check_candidate')
    def test_adapter_invalid_inputs_and_contract_fail_before_execution(self,remote):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        with self.assertRaisesRegex(ValueError,'required'):
            self.store.check_adapter('a'*64,{},'vision_rsi.adapter_fixture','predict',contract,[{'sample_id':'missing','inputs':{}}])
        bad=json.loads(json.dumps(contract));bad['output_schema']['properties']['defects']['items']['type']='unsupported'
        with self.assertRaisesRegex(ValueError,'defined task interface'):
            self.store.check_adapter('a'*64,{},'vision_rsi.adapter_fixture','predict',bad,[contract['example_input']])
        remote.assert_not_called()
        self.assertFalse((self.store.root/('a'*64)).exists())

    @patch('vision_rsi.remote.check_candidate')
    def test_aggregate_case_limit_rejected_before_remote_or_evidence(self,remote):
        from vision_rsi.candidate_runtime import encode_cases
        case={'history':[{'id':'observed','note':'x'*300000}],'actions':[],'budget':1}
        from vision_rsi.strategy_protocol import validate_context
        validate_context(**case)
        payload=encode_cases('vision_rsi.strategy_candidate','propose',[case])
        self.assertGreater(len(payload),64*1024)
        with self.assertRaisesRegex(ValueError,'too large'):
            self.store.check('a'*64,{},'vision_rsi.strategy_candidate','propose',[case]*4)
        remote.assert_not_called()
        self.assertFalse((self.store.root/('a'*64)).exists())
        for cases in ([],[{}]*17,[{'number':float('nan')}]):
            with self.subTest(cases=str(cases)[:40]),self.assertRaises(ValueError):
                encode_cases('vision_rsi.strategy_candidate','propose',cases)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.repo=root/'source';self.repo.mkdir()
        git(self.repo,'init');(self.repo/'vision_rsi').mkdir()
        (self.repo/'vision_rsi/research.py').write_text('BASELINE = True\n')
        (self.repo/'vision_rsi/controller.py').write_text('CONTROLLER = True\n')
        git(self.repo,'add','.');git(self.repo,'-c','user.name=Test','-c','user.email=test@local.invalid','commit','-m','baseline')
        self.store=Candidates(root/'candidates',self.repo);self.addCleanup(self.store.close)

    def test_missing_key_does_not_reserve_strategy_request(self):
        with patch.dict('os.environ',{'VISION_RSI_UNSET':''}), patch('vision_rsi.llm.urlopen') as http:
            config={'model':'deepseek-flash','base_url':'https://example.invalid','api_key_env':'VISION_RSI_UNSET'}
            with self.assertRaises(ValueError):self.store.propose('preflight-missing',{},[],config)
            self.assertIsNone(self.store.db.execute('SELECT id FROM requests WHERE id=?',('preflight-missing',)).fetchone())
            http.assert_not_called()

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

    def test_recommitting_modified_candidate_cannot_relabel_original_proposal(self):
        record=self.store.create(proposal(),{})
        checkout=Path(record['checkout']);name='vision_rsi/strategy_candidate.py'
        (checkout/name).write_text('def choose(rows):\n    return None\n')
        git(checkout,'add',name)
        git(checkout,'-c','user.name=Test','-c','user.email=test@local.invalid','commit','--amend','-m','tampered')
        record['git_revision']=git(checkout,'rev-parse','HEAD')
        import hashlib
        record['source_hashes'][name]=hashlib.sha256((checkout/name).read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'original proposal'):self.store.verify(record)

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
    def test_strategy_rejects_missing_decisions(self,remote):
        record=self.store.create(proposal(),{})
        remote.side_effect=lambda endpoint,request: {'status':'executed_unverified','source_hashes':request['source_hashes'],'observation':{'results':[]}}
        cases=[{'history':[],'actions':[],'budget':1}]
        result=self.store.check_strategy(record['candidate_id'],{'workspace':'/workspace'},'vision_rsi.strategy_candidate',cases)
        self.assertEqual(result['status'],'protocol_failed')
        self.assertIn('result count',result['protocol_failures'][0]['error'])

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
