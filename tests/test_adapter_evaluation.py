import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.adapter_evaluation import evaluate
from vision_rsi.candidates import Candidates,git
import test_event_eval as fixtures
from test_event_eval import event


class AdapterEvaluationTests(unittest.TestCase):
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_detection_contract_does_not_offer_event_metric_tool(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        contract=json.loads(self.contract.read_text())
        contract['acceptance']={'metric':'box_AP','direction':'maximize','threshold':60,
                                'evaluation_protocol':'coco_bbox'}
        self.contract.write_text(json.dumps(contract),encoding='utf-8')
        ledger=Ledger(self.root/'detection-ledger')
        ledger.append('objective','objective',{'summary':'detection task'})
        ledger.append('stage','action',{'summary':'staged','executor':'research-v1','tool':'stage_candidate'})
        ledger.append('stage:result','result',{'summary':'candidate','action':'stage','status':'completed',
                      'observation':{'candidate_id':self.candidate}})
        config={'llm':{'model':'fixture'},'research':{'allow_candidate_checks':True,
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'evaluate_contract','summary':'invalid protocol',
            'question':'q','expected_evidence':'metric','refs':['stage:result'],
            'arguments':{'candidate_id':self.candidate,'module':'vision_rsi.adapter_fixture','function':'predict'}})}
        research_step(config,ledger.directory,steps=1)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertNotIn('evaluate_contract',prompt['available_tools'])
        self.assertNotIn('evaluate_contract',prompt['tools'])
        remote.assert_not_called()
        self.assertFalse(any(e['kind']=='action' and e['payload'].get('tool')=='evaluate_contract' for e in ledger.events()))

    def test_validation_binding_cannot_change_or_disappear_between_steps(self):
        from vision_rsi.controller import bind_validation
        from vision_rsi.ledger import Ledger
        ledger=Ledger(self.root/'binding-ledger')
        ledger.append('objective','objective',{'summary':'fixed development experiment'})
        config={'research':{'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
                          'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        bind_validation(ledger,config);bind_validation(ledger,config)
        self.assertEqual(len(ledger.events()),2)
        with self.assertRaisesRegex(ValueError,'cannot be removed'):bind_validation(ledger,{})
        self.dataset.write_text(json.dumps(dict(self.data,purpose='other')),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'changed before planning'):bind_validation(ledger,config)
        config['research']['validation_dataset']['sha256']=hashlib.sha256(self.dataset.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'binding is frozen'):bind_validation(ledger,config)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_controller_can_evaluate_only_a_staged_candidate_on_configured_data(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        ledger=Ledger(self.root)
        ledger.append('goal','objective',{'summary':'Fixture candidate metric investigation'})
        ledger.append('stage','action',{'summary':'staged fixture','tool':'stage_candidate','executor':'research-v1'})
        ledger.append('stage:result','result',{'summary':'staged','action':'stage','status':'completed',
                      'observation':{'candidate_id':self.candidate}})
        config={'llm':{'model':'fixture'},'remote':{},'research':{'allow_candidate_checks':True,
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'evaluate_contract','summary':'measure',
            'question':'q','expected_evidence':'fixed F1','refs':['stage:result'],
            'arguments':{'candidate_id':self.candidate,'module':'vision_rsi.adapter_fixture','function':'predict'}})}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[]}]}}
        research_step(config,self.root,steps=1)
        result=ledger.events()[-1]['payload']
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['observation']['runtime_status'],'development_metric_not_met')
        self.assertEqual(result['observation']['metric_report']['event_micro_f1'],0)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertIn('evaluate_contract',prompt['available_tools'])
        self.assertEqual(prompt['validation_dataset']['sha256'],config['research']['validation_dataset']['sha256'])
        self.assertNotIn('ground_truth',remote.call_args.args[1])
        # The next persisted planner request must receive numeric failures as
        # structured evidence, rather than a potentially truncated JSON excerpt.
        client.return_value.complete.return_value={'content':json.dumps({'tool':'inspect_repository','summary':'inspect',
            'question':'q','expected_evidence':'source','refs':[]})}
        research_step(config,self.root,steps=1)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        metrics=[row['observation'] for row in prompt['history']
                 if row['observation'].get('kind')=='candidate_development_metric']
        self.assertEqual(len(metrics),1)
        self.assertEqual(metrics[0]['metric_report']['event_micro_f1'],0)
        self.assertFalse(metrics[0]['metric_report']['metric_threshold_met'])
        self.assertEqual(metrics[0]['metric_report']['error_analysis']['worst_labels'][0]['fn'],1)
        self.assertEqual(metrics[0]['metric_report']['error_analysis']['worst_samples'][0]['fn'],1)
        self.assertFalse(metrics[0]['production_acceptance_verified'])

    @patch('vision_rsi.remote.check_candidate')
    def test_configured_dataset_hash_mismatch_refuses_remote(self,remote):
        with self.assertRaisesRegex(ValueError,'dataset changed'):
            evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset,
                     expected_dataset_sha256='0'*64)
        remote.assert_not_called()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);repo=self.root/'repo';repo.mkdir()
        git(repo,'init');(repo/'vision_rsi').mkdir();(repo/'vision_rsi/research.py').write_text('# fixture\n')
        git(repo,'add','.');git(repo,'-c','user.name=Fixture','-c','user.email=fixture@local.invalid','commit','-m','base')
        self.store=Candidates(self.root/'candidates',repo);self.addCleanup(self.store.close)
        proposal={'hypothesis':'fixture metric pipeline','expected_improvement':'testable','evaluation_plan':'development validation',
                  'edits':[{'path':'vision_rsi/adapter_fixture.py','base_sha256':None,'content':'def predict(sample):\n    return {"events": []}\n'}]}
        self.candidate=self.store.create(proposal,{'fixture':True})['candidate_id']
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
        metric_contract=fixtures.EventEvaluationTests.contract(None)
        contract.update(acceptance=metric_contract['acceptance'],output_schema=metric_contract['output_schema'],example_output={'events':[]})
        self.contract=self.root/'contract.json';self.contract.write_text(json.dumps(contract),encoding='utf-8')
        sample=dict(contract['example_input'],sample_id='clip1')
        self.dataset=self.root/'validation.json'
        self.data={'purpose':'development_validation','samples':[sample],
                   'ground_truth':{'labels':['action'],'samples':[{'sample_id':'clip1','events':[event(0,1)]}]}}
        self.dataset.write_text(json.dumps(self.data),encoding='utf-8')

    @patch('vision_rsi.remote.check_candidate')
    def test_interface_pass_with_wrong_output_fails_metric_and_reuses_runtime(self,remote):
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[]}]}}
        result=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result['status'],'development_metric_not_met')
        self.assertEqual(result['metric_report']['event_micro_f1'],0)
        self.assertFalse(result['quality_verified']);self.assertFalse(result['agent_adopted'])
        repeated=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result,repeated)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_metric_met_is_not_production_acceptance_or_adoption(self,remote):
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[event(0,1)]}]}}
        result=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result['status'],'development_metric_met')
        self.assertEqual(result['metric_report']['event_micro_f1'],1)
        self.assertFalse(result['quality_verified']);self.assertFalse(result['capability_registered'])
        self.assertNotIn('ground_truth',json.dumps(remote.call_args.args[1]))

    @patch('vision_rsi.remote.check_candidate')
    def test_dataset_scope_and_coverage_refuse_execution(self,remote):
        for changed in (dict(self.data,purpose='hidden_test'),dict(self.data,ground_truth={'labels':['action'],'samples':[]})):
            self.dataset.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(ValueError):evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        remote.assert_not_called()
