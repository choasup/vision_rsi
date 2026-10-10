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

    @patch('vision_rsi.remote.check_candidate')
    def test_bundle_metric_carries_runtime_identity(self,remote):
        from test_candidate_runtime import identity
        from vision_rsi.runner import digest
        from vision_rsi.bundle_evaluation import evaluate_bundle
        self.prepare(remote);base=remote.side_effect;value=identity()
        remote.side_effect=lambda *args:dict(base(*args),runtime_identity=value,runtime_identity_sha256=digest(value))
        self.data['purpose']='development_validation';self.dataset.write_text(json.dumps(self.data))
        report=evaluate_bundle(self.bundle['path'],self.dataset,{},self.root/'evaluations')
        self.assertEqual(report['identity']['runtime_identity_sha256'],digest(value))

    def runtime_accepted(self,remote):
        from test_candidate_runtime import identity
        from vision_rsi.runner import digest
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        base=remote.side_effect;value=identity()
        remote.side_effect=lambda *args:dict(base(*args),runtime_identity=value,runtime_identity_sha256=digest(value))
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        return registry,delivery,value

    @patch('vision_rsi.remote.check_candidate')
    def test_selected_runtime_pinned_and_report_scope_remains_partial(self,remote):
        from vision_rsi.runner import digest
        registry,delivery,value=self.runtime_accepted(remote)
        args=(registry,self.session,delivery['version'],self.dataset,{},30)
        result=check(*args)
        self.assertTrue(result['selected_runtime_consistent'])
        self.assertFalse(result['environment_fully_verified'])
        self.assertEqual(remote.call_args.args[1]['expected_runtime_identity_sha256'],digest(value))
        self.assertEqual(check(*args),result);self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_changed_runtime_refused_and_measurement_not_retried(self,remote):
        registry,delivery,value=self.runtime_accepted(remote)
        value['kernel_release']='changed-runtime'
        args=(registry,self.session,delivery['version'],self.dataset,{},30)
        with self.assertRaisesRegex(ValueError,'runtime differs'):check(*args)
        with self.assertRaisesRegex(RuntimeError,'uncertain'):check(*args)
        self.assertEqual(remote.call_count,3)

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

    @patch('vision_rsi.remote.check_candidate')
    def test_rehashed_false_metric_refused_before_serving_dispatch(self,remote):
        from vision_rsi.runner import atomic_json,digest
        registry,delivery=self.accepted(remote)
        path=registry.root/self.session['task_id']/'candidate-acceptance'/'acceptance.json'
        report=json.loads(path.read_text())
        report['metric_report']['tp']+=1
        report['report_sha256']=digest({k:v for k,v in report.items() if k!='report_sha256'})
        atomic_json(path,report)
        with registry.db:
            registry.db.execute('UPDATE candidate_acceptance_slots SET report_hash=? WHERE task_id=?',
                                (report['report_sha256'],self.session['task_id']))
        with self.assertRaisesRegex(ValueError,'independently recomputed'):
            check(registry,self.session,delivery['version'],self.dataset,{},30)
        self.assertEqual(remote.call_count,2)
        self.assertFalse((registry.root/self.session['task_id']/'candidate-serving').exists())

    @patch('vision_rsi.remote.check_candidate')
    def test_cached_serving_recomputes_metric_without_remote_calls(self,remote):
        from vision_rsi.runner import atomic_json,digest
        registry,delivery=self.accepted(remote)
        check(registry,self.session,delivery['version'],self.dataset,{},30)
        path=registry.root/self.session['task_id']/'candidate-acceptance'/'acceptance.json'
        report=json.loads(path.read_text())
        report['metric_report']['threshold']=0
        report['report_sha256']=digest({k:v for k,v in report.items() if k!='report_sha256'})
        atomic_json(path,report)
        with registry.db:
            registry.db.execute('UPDATE candidate_acceptance_slots SET report_hash=? WHERE task_id=?',
                                (report['report_sha256'],self.session['task_id']))
        with self.assertRaisesRegex(ValueError,'independently recomputed'):
            check(registry,self.session,delivery['version'],self.dataset,{},30,cached_only=True)
        self.assertEqual(remote.call_count,4)
