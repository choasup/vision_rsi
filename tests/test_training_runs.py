import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.training_runs import TrainingRuns,submit,observe

REMOTE={'ssh_host':'fixture','workspace':'/workspace','ssh_port':22,'python':'python3'}


def plan(identity='one'):
    return {'status':'ready_to_submit','session_id':'session','task_id':'task','plan_id':identity,'plan_path':'ignored-fixture-plan.json',
            'contract':{'budget':{'gpu_hours':.03}},'recipe':{'world_size':1},
            'scheduler':{'gpu_devices':[0],'timeout_seconds':40,'gpu_hours_budget':.03}}


class TrainingRunsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=TrainingRuns(self.temp.name);self.addCleanup(self.store.close)
    def test_reservations_are_shared_and_duplicates_do_not_charge_twice(self):
        first,created=self.store.reserve(plan(),REMOTE)
        self.assertTrue(created)
        duplicate,created=self.store.reserve(plan(),REMOTE)
        self.assertFalse(created);self.assertEqual(first['run_id'],duplicate['run_id'])
        self.store.reserve(plan('two'),REMOTE)
        with self.assertRaisesRegex(ValueError,'exhausted'):self.store.reserve(plan('three'),REMOTE)
        self.store.update(first['run_id'],'completed',first['details'],actual=.001)
        self.store.reserve(plan('three'),REMOTE)
    @patch('vision_rsi.training_runs.deploy_training',side_effect=RuntimeError('network unavailable'))
    def test_deployment_failure_releases_unused_reservation(self,_):
        with self.assertRaises(RuntimeError):submit(plan(),REMOTE,self.store)
        record=self.store.list('session')[0]
        self.assertEqual(record['status'],'deployment_failed');self.assertEqual(record['actual_gpu_hours'],0)
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.training_runs.deploy_training')
    def test_lost_submit_response_retains_budget_and_reconciles_same_id(self,deploy,request):
        deploy.return_value={'entry':'/workspace/train.py','recipe':'/workspace/recipe.json','dependencies_ready':True}
        request.side_effect=TimeoutError('response lost')
        with self.assertRaises(TimeoutError):submit(plan(),REMOTE,self.store)
        record=self.store.list('session')[0]
        self.assertEqual(record['status'],'submission_uncertain');self.assertIsNone(record['actual_gpu_hours'])
        self.assertTrue(submit(plan(),REMOTE,self.store)['reused']);self.assertEqual(request.call_count,1)
        request.side_effect=None;request.return_value={'status':'completed','gpu_hours':.002}
        result=observe(record['run_id'],REMOTE,self.store)
        self.assertEqual(result['actual_gpu_hours'],.002)
        self.assertEqual(request.call_args.args[2],record['run_id'])
    @patch('vision_rsi.training_runs.job_request')
    def test_rejects_other_destination_and_invalid_accounting(self,request):
        record,_=self.store.reserve(plan(),REMOTE)
        with self.assertRaisesRegex(ValueError,'another SSH'):observe(record['run_id'],dict(REMOTE,ssh_port=2222),self.store)
        request.assert_not_called()
        request.return_value={'status':'completed','gpu_hours':float('nan')}
        with self.assertRaisesRegex(ValueError,'accounting'):observe(record['run_id'],REMOTE,self.store)
        self.assertIsNone(self.store.get(record['run_id'])['actual_gpu_hours'])


class DeploymentValidationTests(unittest.TestCase):
    def test_source_drift_is_rejected_before_ssh(self):
        from vision_rsi.remote import deploy_training
        with patch('vision_rsi.remote.subprocess.run') as ssh:
            with self.assertRaisesRegex(ValueError,'Source changed'):deploy_training(REMOTE,{'source_hashes':{}})
            ssh.assert_not_called()
    def test_remote_rejects_path_escape_before_writing(self):
        from vision_rsi.deployment import deploy
        with self.assertRaises(ValueError):deploy({'workspace':'/workspace','files':{'../escape.py':'Zml4dHVyZQ=='}})
