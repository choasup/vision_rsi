import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.jobs import dispatch, validate


class JobsTests(unittest.TestCase):
    def test_path_and_id_validation(self):
        for workspace in ['', '/', 'relative', '/workspace/../root']:
            with self.assertRaises(ValueError):
                validate({'workspace': workspace, 'job_id': 'safe'})
        with self.assertRaises(ValueError):
            validate({'workspace': '/workspace', 'job_id': '../escape'})

    @patch('vision_rsi.jobs.validate')
    @patch('vision_rsi.jobs.subprocess.Popen')
    def test_duplicate_never_relaunches_and_conflicts_rejected(self, popen, _):
        with tempfile.TemporaryDirectory() as folder:
            request = {'workspace': folder, 'job_id': 'job1', 'action': 'submit',
                       'spec': {'argv': ['python3', '-c', 'print(1)'], 'timeout_seconds': 5},
                       'worker_source': '# fixture'}
            self.assertFalse(dispatch(request)['duplicate'])
            self.assertTrue(dispatch(request)['duplicate'])
            self.assertEqual(popen.call_count, 1)
            request['spec']['argv'][-1] = 'print(2)'
            with self.assertRaises(ValueError):
                dispatch(request)
            self.assertEqual(popen.call_count, 1)

    @patch('vision_rsi.jobs.validate')
    def test_uncertain_submission_and_lost_worker(self, _):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder)/'jobs'/'job1'
            job.mkdir(parents=True)
            request = {'workspace': folder, 'job_id': 'job1', 'action': 'submit',
                       'spec': {'argv': ['python3'], 'timeout_seconds': 5}}
            with self.assertRaises(RuntimeError):
                dispatch(request)
            (job/'state.json').write_text(json.dumps({'status': 'running', 'worker_pid': 123,
                                                     'process_identity': {'start_ticks': 'old'}}))
            request['action'] = 'status'
            with patch('vision_rsi.jobs.process_identity', return_value={'start_ticks': 'new'}):
                self.assertEqual(dispatch(request)['status'], 'lost')

class GpuJobAdmissionTests(unittest.TestCase):
    def test_explicit_budget_and_device_validation(self):
        from vision_rsi.jobs import validate_spec
        spec={'argv':['python3','train.py'],'timeout_seconds':3600,'gpu_devices':list(range(8)),'gpu_hours_budget':8.1}
        self.assertEqual(validate_spec(spec),list(range(8)))
        for patch_values in [{'gpu_hours_budget':8},{'gpu_hours_budget':float('nan')},{'gpu_devices':[0,0]},
                             {'gpu_devices':[True]},{'gpu_devices':[8]},{'timeout_seconds':float('inf')}]:
            with self.assertRaises(ValueError):validate_spec(dict(spec,**patch_values))
        del spec['gpu_hours_budget']
        with self.assertRaises(ValueError):validate_spec(spec)

    def test_cpu_does_not_accidentally_gain_gpu_or_long_runtime(self):
        from vision_rsi.jobs import validate_spec
        self.assertEqual(validate_spec({'argv':['python3'],'timeout_seconds':5}),[])
        with self.assertRaises(ValueError):validate_spec({'argv':['python3'],'timeout_seconds':3600})
