import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.adapter_evaluation import evaluate
from vision_rsi.candidates import Candidates,git
import test_event_eval as fixtures
from test_event_eval import event


class AdapterEvaluationTests(unittest.TestCase):
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
