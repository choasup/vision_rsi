import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from vision_rsi.dashboard_training import advance_training
from vision_rsi.training_runs import TrainingRuns
from test_training_runs import plan, REMOTE

class DashboardTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.session={'session_id':'session'}

    @patch('vision_rsi.dashboard_training.prepare')
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.training_runs.prepare_coco_backend')
    def test_submit_once_then_observe_same_run(self,backend,request,prepare):
        prepare.return_value=dict(plan(),blockers=[])
        backend.return_value={'deployment':{},'resource_preflight':{},'output_directory':'/workspace/out','argv':['python3','train.py']}
        request.side_effect=[{'status':'submitted'},{'status':'running'}]
        first=advance_training(self.session,{'remote':REMOTE},self.root)
        second=advance_training(self.session,{'remote':REMOTE},self.root)
        self.assertEqual(first['status'],'submitted');self.assertEqual(second['status'],'running')
        self.assertEqual(first['run_id'],second['run_id'])
        self.assertEqual([c.args[1] for c in request.call_args_list],['submit','status'])
        self.assertEqual(prepare.call_count,1)

    @patch('vision_rsi.dashboard_training.prepare')
    @patch('vision_rsi.training_runs.job_request')
    def test_missing_resources_block_without_reservation(self,request,prepare):
        prepare.return_value=dict(plan(),status='blocked',blockers=['数据路径未配置'])
        result=advance_training(self.session,{},self.root)
        self.assertEqual(result['status'],'blocked');self.assertIn('数据路径',result['message'])
        request.assert_not_called()
        runs=TrainingRuns(self.root/'training-runs')
        try:self.assertEqual(runs.list('session'),[])
        finally:runs.close()

    @patch('vision_rsi.dashboard_training.prepare')
    @patch('vision_rsi.training_runs.job_request')
    @patch('vision_rsi.training_runs.prepare_coco_backend')
    def test_uncertain_submission_reconciles_without_resubmit(self,backend,request,prepare):
        prepare.return_value=dict(plan(),blockers=[])
        backend.return_value={'deployment':{},'resource_preflight':{},'output_directory':'/workspace/out','argv':['python3','train.py']}
        request.side_effect=[TimeoutError('response lost'),{'status':'running'}]
        self.assertEqual(advance_training(self.session,{'remote':REMOTE},self.root)['status'],'blocked')
        self.assertEqual(advance_training(self.session,{'remote':REMOTE},self.root)['status'],'running')
        self.assertEqual([c.args[1] for c in request.call_args_list],['submit','status'])
