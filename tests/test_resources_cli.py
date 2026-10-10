import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.resources_cli import step
from vision_rsi.runner import digest


class ResourceCliTests(unittest.TestCase):
    def test_running_and_lost_jobs_never_create_duplicate_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]; specs={}; status='running'
            def request(remote,action,job,spec=None):
                calls.append(action)
                if action=='submit':specs[job]=spec;return {'spec_hash':digest(spec)}
                return {'status':status,'spec_hash':digest(specs[job])}
            first=step({},'/assets/coco',tmp,request)
            self.assertEqual(step({},'/assets/coco',tmp,request)['job_id'],first['job_id'])
            status='lost'
            self.assertEqual(step({},'/assets/coco',tmp,request)['status'],'lost')
            self.assertEqual(calls.count('submit'),1)

    def test_uncertain_submit_keeps_original_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            def request(*args):raise TimeoutError('transport unknown')
            with self.assertRaises(TimeoutError):step({},'/assets/coco',tmp,request)
            path=Path(tmp)/'resources.json'; saved=path.read_bytes();calls=[]
            def observe(remote,action,job,spec=None):
                calls.append(action);raise RuntimeError('Unknown job ID')
            with self.assertRaises(RuntimeError):step({},'/assets/coco',tmp,observe)
            self.assertEqual(calls,['status']);self.assertEqual(path.read_bytes(),saved)

    def test_only_completed_partial_allows_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs={};calls=[]
            def request(remote,action,job,spec=None):
                calls.append(action)
                if action=='submit':specs[job]=spec;return {'spec_hash':digest(spec)}
                if action=='status':return {'status':'completed','spec_hash':digest(specs[job]),'gpu_count':0,'gpu_hours':0}
                return {'log':json.dumps({'status':'partial','resources':[],'gpu_used':False,'training_started':False})}
            first=step({},'/assets/coco',tmp,request)
            second=step({},'/assets/coco',tmp,request)
            self.assertNotEqual(first['job_id'],second['job_id'])
            self.assertEqual(calls,['submit','status','logs','submit'])
            with self.assertRaises(ValueError):step({},'/different',tmp,request)

    def test_mismatched_remote_spec_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            def request(remote,action,job,spec=None):
                return {'spec_hash':digest(spec)} if action=='submit' else {'status':'completed','spec_hash':'0'*64}
            step({},'/assets/coco',tmp,request)
            with self.assertRaises(ValueError):step({},'/assets/coco',tmp,request)

    def test_verified_downloads_do_not_claim_dataset_ready_or_restart(self):
        from vision_rsi.resource_bootstrap import RESOURCES
        with tempfile.TemporaryDirectory() as tmp:
            specs={};calls=[]
            rows=[{'asset':a,'status':'downloaded','downloaded_bytes':a['bytes'],
                   'sha256':a.get('sha256_prefix','')+'0'*(64-len(a.get('sha256_prefix','')))} for a in RESOURCES]
            def request(remote,action,job,spec=None):
                calls.append(action)
                if action=='submit':specs[job]=spec;return {'spec_hash':digest(spec)}
                if action=='status':return {'status':'completed','spec_hash':digest(specs[job]),'gpu_count':0,'gpu_hours':0}
                return {'log':json.dumps({'status':'downloads_verified','resources':rows,'gpu_used':False,'training_started':False})}
            step({},'/assets/coco',tmp,request)
            result=step({},'/assets/coco',tmp,request)
            self.assertEqual(result['status'],'downloads_verified')
            self.assertFalse(result['dataset_ready']);self.assertEqual(calls.count('submit'),1)
            rows[0]['sha256']='0'*64
            with self.assertRaises(ValueError):step({},'/assets/coco',tmp,request)
