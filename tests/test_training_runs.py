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
    @patch('vision_rsi.training_runs.deploy_training')
    @patch('vision_rsi.training_runs.job_request')
    def test_old_ready_plan_cannot_bypass_unenforced_resource_caps(self,request,deploy):
        for key in ('llm_calls','llm_tokens','wall_seconds','cpu_seconds','custom_cap'):
            candidate=plan(key);candidate['contract']['budget'][key]=1
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'cannot enforce budget.'+key):
                submit(candidate,REMOTE,self.store)
        request.assert_not_called();deploy.assert_not_called()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],0)

    @patch('vision_rsi.training_runs.job_request')
    def test_logs_reconcile_terminal_status_and_campaign_progress(self,request):
        from vision_rsi.campaign import project
        record,_=self.store.reserve(plan(),REMOTE)
        request.side_effect=[{'log':'still training'}, {'status':'completed','gpu_hours':.002}]
        result=observe(record['run_id'],REMOTE,self.store,'logs')
        self.assertEqual(result['log'],'still training')
        self.assertEqual(result['actual_gpu_hours'],.002)
        self.assertEqual(self.store.get(record['run_id'])['status'],'completed')
        state={}
        project(state,{'kind':'logs'},result)
        self.assertEqual(state['run_status'],'completed')
        self.assertEqual(state['status'],'processing_result')
        self.assertEqual([call.args[1] for call in request.call_args_list],['logs','status'])

    @patch('vision_rsi.training_runs.job_request')
    def test_log_text_cannot_settle_budget_when_status_is_unavailable(self,request):
        record,_=self.store.reserve(plan(),REMOTE)
        request.side_effect=[{'log':'completed gpu_hours=0'},TimeoutError('status unavailable')]
        with self.assertRaises(TimeoutError):observe(record['run_id'],REMOTE,self.store,'logs')
        saved=self.store.get(record['run_id'])
        self.assertIsNone(saved['actual_gpu_hours'])
        self.assertEqual(saved['status'],record['status'])

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
    def test_remaining_budget_includes_uncertain_reservations(self):
        record,_=self.store.reserve(plan(),REMOTE)
        self.assertAlmostEqual(self.store.remaining('session',.03),.03-45/3600)
        with self.assertRaises(ValueError):self.store.remaining('session',1)
        self.store.update(record['run_id'],'completed',record['details'],actual=.001)
        self.assertAlmostEqual(self.store.remaining('session',.03),.029)
    @patch('vision_rsi.training_runs.deploy_training',side_effect=RuntimeError('network unavailable'))
    def test_deployment_failure_releases_unused_reservation(self,_):
        with self.assertRaises(RuntimeError):submit(plan(),REMOTE,self.store)
        record=self.store.list('session')[0]
        self.assertEqual(record['status'],'deployment_failed');self.assertEqual(record['actual_gpu_hours'],0)
    @patch('vision_rsi.training_runs.resource_preflight',return_value={'status':'resources_verified'})
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.training_runs.deploy_training')
    def test_lost_submit_response_retains_budget_and_reconciles_same_id(self,deploy,request,preflight):
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
    @patch('vision_rsi.training_runs.resource_preflight',side_effect=RuntimeError('missing training images'))
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.training_runs.deploy_training',return_value={'dependencies_ready':True})
    def test_resource_failure_never_submits_gpu_and_releases_unused_reservation(self,deploy,request,preflight):
        with self.assertRaisesRegex(RuntimeError,'missing training'):submit(plan(),REMOTE,self.store)
        request.assert_not_called();preflight.assert_called_once()
        record=self.store.list('session')[0]
        self.assertEqual(record['status'],'deployment_failed');self.assertEqual(record['actual_gpu_hours'],0)
        self.assertEqual(self.store.remaining('session',.03),.03)
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

class CollectionCoordinatorTests(unittest.TestCase):
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.remote.collect_training')
    def test_receipt_persisted_and_fixture_is_not_registered(self,collector,request):
        import json
        from pathlib import Path
        from vision_rsi.runner import digest
        from vision_rsi.training_runs import collect
        from test_acceptance import evidence
        frozen,receipt=evidence(100,True)
        with tempfile.TemporaryDirectory() as root:
            store=TrainingRuns(root)
            try:
                base=dict(frozen,session_id='session',task_id='task',status='ready_to_submit',scheduler=plan()['scheduler'])
                base['contract']['budget']={'gpu_hours':.03}
                path=Path(root)/'plan.json';path.write_text(json.dumps(base))
                p=dict(base,plan_id=digest(base),plan_path=str(path))
                record,_=store.reserve(p,REMOTE)
                details=record['details'];details['output_directory']='/workspace/training/task/'+record['run_id']
                store.update(record['run_id'],'submitted',details)
                request.return_value={'status':'completed','gpu_hours':.001}
                receipt['run_id']=record['run_id'];collector.return_value=receipt
                result=collect(record['run_id'],REMOTE,store)
                self.assertEqual(result['details']['acceptance_review']['status'],'not_met')
                self.assertTrue(Path(result['details']['receipt_path']).exists())
                self.assertEqual(result['actual_gpu_hours'],.001)
            finally:store.close()

class ResumeCoordinatorTests(unittest.TestCase):
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.remote.collect_training')
    @patch('vision_rsi.training_runs.resource_preflight')
    def test_legacy_plan_caps_block_resume_before_checkpoint_or_gpu(self,preflight,checkpoint,request):
        import json
        from pathlib import Path
        from vision_rsi.runner import digest
        from vision_rsi.training_runs import resume
        # Represent a frozen legacy plan accepted before budget-field admission existed.
        path=Path(self.plan['plan_path']);base=json.loads(path.read_text())
        base['contract']['budget']['wall_seconds']=0
        path.write_text(json.dumps(base))
        with self.store.db:
            self.store.db.execute('UPDATE runs SET plan=? WHERE id=?',(digest(base),self.original))
        request.return_value={'status':'cancelled','gpu_hours':.001}
        with self.assertRaisesRegex(ValueError,'cannot enforce budget.wall_seconds'):
            resume(self.original,REMOTE,self.store)
        self.assertEqual([call.args[1] for call in request.call_args_list],['status'])
        checkpoint.assert_not_called();preflight.assert_not_called()
        self.assertEqual(len(self.store.list('session')),1)

    def setUp(self):
        import json
        from pathlib import Path
        from vision_rsi.runner import digest
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=TrainingRuns(self.temp.name);self.addCleanup(self.store.close)
        base=plan();base.pop('plan_id');base.pop('plan_path')
        path=Path(self.temp.name)/'plan.json';path.write_text(json.dumps(base))
        self.plan=dict(base,plan_id=digest(base),plan_path=str(path))
        record,_=self.store.reserve(self.plan,REMOTE);self.original=record['run_id']
        details=record['details'];details.update(deployment={'resume_protocol':2},output_directory='/workspace/training/task/'+self.original,
            spec={'argv':['python3','train.py','--output','/workspace/training/task/'+self.original]})
        self.store.update(self.original,'cancelled',details,actual=.001)
    @patch('vision_rsi.training_runs.resource_preflight',return_value={'status':'resources_verified'})
    @patch('vision_rsi.remote.collect_training')
    @patch('vision_rsi.training_runs.job_request')
    def test_resume_has_stable_id_frozen_checkpoint_and_shared_budget(self,request,inspect,preflight):
        from vision_rsi.training_runs import resume
        request.side_effect=lambda remote,action,run_id,*args: {'status':'cancelled','gpu_hours':.001} if action=='status' else {'job_id':run_id}
        inspect.return_value={'checkpoint_sha256':'a'*64,'progress':{'status':'interrupted'}}
        first=resume(self.original,REMOTE,self.store)
        second=resume(self.original,REMOTE,self.store)
        self.assertTrue(second['reused']);self.assertEqual(first['run_id'],second['run_id'])
        self.assertNotEqual(first['run_id'],self.original)
        self.assertEqual(first['details']['output_run_id'],self.original)
        argv=first['details']['spec']['argv']
        self.assertIn('--resume',argv);self.assertEqual(argv[-2:],['--checkpoint-sha256','a'*64])
        self.assertEqual(len(self.store.list('session')),2)
        inspect.return_value['checkpoint_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'owns this Training output'):resume(self.original,REMOTE,self.store)
    @patch('vision_rsi.training_runs.resource_preflight',side_effect=RuntimeError('resource missing'))
    @patch('vision_rsi.remote.collect_training')
    @patch('vision_rsi.training_runs.job_request')
    def test_resume_resource_failure_cannot_submit_gpu(self,request,inspect,preflight):
        from vision_rsi.training_runs import resume
        request.return_value={'status':'cancelled','gpu_hours':.001}
        inspect.return_value={'checkpoint_sha256':'a'*64,'progress':{'status':'interrupted'}}
        with self.assertRaisesRegex(RuntimeError,'resource missing'):resume(self.original,REMOTE,self.store)
        self.assertEqual([call.args[1] for call in request.call_args_list],['status'])
        resumed=[row for row in self.store.list('session') if row['run_id']!=self.original][0]
        self.assertEqual(resumed['status'],'resume_preflight_failed');self.assertEqual(resumed['actual_gpu_hours'],0)
    @patch('vision_rsi.remote.collect_training')
    @patch('vision_rsi.training_runs.job_request')
    def test_active_and_completed_evaluation_cannot_resume(self,request,inspect):
        from vision_rsi.training_runs import resume
        request.return_value={'status':'running'}
        with self.assertRaisesRegex(ValueError,'active'):resume(self.original,REMOTE,self.store)
        inspect.assert_not_called()
        request.return_value={'status':'completed','gpu_hours':.001}
        inspect.return_value={'checkpoint_sha256':'a'*64,'progress':{'status':'evaluated'}}
        with self.assertRaisesRegex(ValueError,'already evaluated'):resume(self.original,REMOTE,self.store)
    def test_resume_reservation_is_capped_to_remaining_budget(self):
        record=self.store.get(self.original)
        self.store.update(self.original,'cancelled',record['details'],actual=.027)
        record,created=self.store.reserve(self.plan,REMOTE,attempt='resume',cap_to_remaining=True)
        self.assertTrue(created);self.assertLess(record['reserved_gpu_hours'],.0031)
        self.assertLess(record['details']['scheduler']['timeout_seconds'],40)
