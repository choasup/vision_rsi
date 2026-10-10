import json
import unittest
from unittest.mock import patch

import test_task_acceptance as fixtures
from test_event_eval import event
from vision_rsi.candidate_serving import check
from vision_rsi.task_acceptance import accept


class CandidateServingTests(unittest.TestCase):
    setUp=fixtures.TaskAcceptanceTests.setUp
    prepare=fixtures.TaskAcceptanceTests.prepare
    registry=fixtures.TaskAcceptanceTests.registry

    def accepted(self,remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        return registry,delivery

    @patch('vision_rsi.remote.check_candidate')
    def test_two_fresh_checks_cache_and_no_promotion(self,remote):
        registry,delivery=self.accepted(remote)
        args=(registry,self.session,delivery['version'],self.dataset,{},30)
        result=check(*args)
        self.assertEqual(result['status'],'serving_contract_checks_met')
        self.assertEqual(remote.call_count,4)
        self.assertNotEqual(result['trials'][0]['execution_path'],result['trials'][1]['execution_path'])
        self.assertEqual(check(*args),result);self.assertEqual(remote.call_count,4)
        self.assertEqual(check(registry,self.session,delivery['version'],self.dataset,{},30.0),result)
        self.assertFalse(result['production_accepted']);self.assertFalse(result['environment_fully_verified'])
        with self.assertRaisesRegex(ValueError,'No validated'):registry.resolve_version(self.session['task_id'])
        with self.assertRaisesRegex(ValueError,'slot frozen'):
            check(registry,self.session,delivery['version'],self.dataset,{},60)
        root=registry.root/self.session['task_id']/'candidate-serving'
        (root/'trial-1.json').write_bytes((root/'trial-0.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'trial identity differs'):check(*args)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_wrong_output_or_slow_output_preserved_as_not_met(self,remote):
        registry,delivery=self.accepted(remote)
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        with patch('vision_rsi.candidate_serving.time.perf_counter',side_effect=[0,2,3,5]):
            result=check(registry,self.session,delivery['version'],self.dataset,{},1)
        self.assertEqual(result['status'],'serving_contract_checks_not_met')
        self.assertTrue(all(not row['outputs_match_acceptance'] and not row['latency_target_met'] for row in result['trials']))
        self.assertEqual(check(registry,self.session,delivery['version'],self.dataset,{},1),result)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_measurement_never_repeated(self,remote):
        registry,delivery=self.accepted(remote);remote.side_effect=RuntimeError('connection lost')
        args=(registry,self.session,delivery['version'],self.dataset,{},30)
        with self.assertRaisesRegex(RuntimeError,'connection lost'):check(*args)
        with self.assertRaisesRegex(RuntimeError,'uncertain'):check(*args)
        self.assertEqual(remote.call_count,3)

    @patch('vision_rsi.remote.check_candidate')
    def test_input_change_and_driver_change_refused_before_call(self,remote):
        registry,delivery=self.accepted(remote)
        args=(registry,self.session,delivery['version'],self.dataset,{},30)
        self.dataset.write_text(self.dataset.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'inputs or remote differ'):check(*args)
        self.assertEqual(remote.call_count,2)
        self.dataset.write_text(self.dataset.read_text().rstrip())
        # Source identity is validated independently from metric success.
        original=__import__('hashlib').sha256
        class Changed:
            def hexdigest(self):return '0'*64
        def changed(raw=b''):
            return Changed() if raw.startswith(b'"""Remote CPU-only') else original(raw)
        with patch('vision_rsi.candidate_serving.hashlib.sha256',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'implementation changed'):check(*args)
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_metric_failure_cannot_enter_serving_checks(self,remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        with self.assertRaisesRegex(ValueError,'metric must be met'):
            check(registry,self.session,delivery['version'],self.dataset,{},30)
        self.assertEqual(remote.call_count,2)
