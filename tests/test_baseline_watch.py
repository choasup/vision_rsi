import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.baseline_watch import advance
from vision_rsi.runner import digest


class WatchTests(unittest.TestCase):
    def setup_record(self,root):
        record={'job_id':'baseline-cpu-test-a0','remote':{},
                'spec':{'timeout_seconds':300,'gpu_devices':[],'gpu_hours_budget':0},
                'observation_context':{'identity':'1'*64}}
        path=root/'baseline-eval-job.json';path.write_text(json.dumps(record))
        active=root/'baseline-active.json';active.write_text(json.dumps({'manifest':str(path),'job_id':record['job_id']}))
        return record,active

    def response(self,record):
        return {'status':'completed','spec_hash':digest(record['spec']),'gpu_count':0,'gpu_hours':0}

    def report(self):
        return {'identity':'1'*64,'gpu_used':False,'training_started':False,'capability_registered':False,
                'total_images':5000,'processed_images':17,'status':'partial','coco_evaluated':False}

    def test_quota_counts_imported_history_and_cannot_increase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record,active=self.setup_record(root);calls=[]
            def request(remote,action,job,spec=None):
                calls.append(action)
                return self.response(record) if action=='status' else {'log':json.dumps(self.report())}
            self.assertEqual(advance(active,1,request=request)['status'],'step_budget_exhausted')
            self.assertNotIn('submit',calls)
            with self.assertRaises(ValueError):advance(active,2,request=request)

    def test_uncertain_submit_persists_new_handle_and_never_resubmits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record,active=self.setup_record(root);calls=[]
            def request(remote,action,job,spec=None):
                calls.append((action,job))
                if action=='submit':raise TimeoutError('unknown submit outcome')
                if job.endswith('a1'):return {'status':'lost','spec_hash':digest(record['spec'])}
                return self.response(record) if action=='status' else {'log':json.dumps(self.report())}
            with self.assertRaises(TimeoutError):advance(active,2,request=request)
            self.assertEqual(json.loads(active.read_text())['job_id'],'baseline-cpu-test-a1')
            self.assertEqual(advance(active,2,request=request)['status'],'lost')
            self.assertEqual(sum(action=='submit' for action,job in calls),1)

    def test_running_and_foreground_deadline_do_not_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record,active=self.setup_record(root);calls=[];status='running'
            def request(remote,action,job,spec=None):
                calls.append(action)
                return dict(self.response(record),status=status) if action=='status' else {'log':json.dumps(self.report())}
            self.assertEqual(advance(active,2,request=request)['status'],'running')
            status='completed'
            self.assertEqual(advance(active,2,False,request)['status'],'foreground_deadline')
            self.assertNotIn('submit',calls)

    def test_completed_coverage_regression_stops_new_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record,active=self.setup_record(root);calls=[];processed=17
            def request(remote,action,job,spec=None):
                calls.append(action)
                if action=='submit':return {'spec_hash':digest(spec)}
                if action=='status':return self.response(record)
                return {'log':json.dumps(dict(self.report(),processed_images=processed))}
            self.assertEqual(advance(active,3,request=request)['status'],'submitted')
            processed=16
            with self.assertRaises(ValueError):advance(active,3,request=request)
            self.assertEqual(calls.count('submit'),1)
