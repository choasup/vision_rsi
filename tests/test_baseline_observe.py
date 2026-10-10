import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision_rsi.baseline_observe import observe
from vision_rsi.runner import digest


class BaselineObserveTests(unittest.TestCase):
    def setUp(self):
        self.record={'remote':{'ssh_host':'root@example','workspace':'/project'},'job_id':'baseline-test',
                     'spec':{'gpu_devices':[],'gpu_hours_budget':0},
                     'observation_context':{'bundle_directory':'/project/releases/'+'1'*64,'bundle_id':'1'*64,
                     'dataset_root':'/project/data','output_directory':'/project/results','identity':'2'*64,'annotation_sha256':'3'*64}}

    def test_observes_lost_as_lost_without_submitting_or_claiming_quality(self):
        with patch('vision_rsi.baseline_observe.job_request',return_value={'status':'lost','spec_hash':digest(self.record['spec'])}) as remote, \
             patch('vision_rsi.baseline_observe.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'read_only':True,'quality_verified':False,'saved_prediction_files':17}),stderr='')):
            result=observe(self.record)
            self.assertEqual(result['worker_status'],'lost');self.assertFalse(result['capability_registered'])
            remote.assert_called_once_with(self.record['remote'],'status',self.record['job_id'])

    def test_source_mismatch_and_missing_context_fail_closed(self):
        with patch('vision_rsi.baseline_observe.job_request',return_value={'status':'completed','spec_hash':'0'*64}), \
             patch('vision_rsi.baseline_observe.subprocess.run') as ssh:
            with self.assertRaises(ValueError):observe(self.record)
            ssh.assert_not_called()
        record=copy.deepcopy(self.record);record.pop('observation_context')
        with patch('vision_rsi.baseline_observe.job_request') as remote:
            with self.assertRaises(ValueError):observe(record)
            remote.assert_not_called()

    def test_unknown_status_is_not_treated_as_terminal_and_invalid_audit_rejected(self):
        with patch('vision_rsi.baseline_observe.job_request',side_effect=TimeoutError('unknown')), \
             patch('vision_rsi.baseline_observe.subprocess.run') as ssh:
            with self.assertRaises(TimeoutError):observe(self.record)
            ssh.assert_not_called()
        invalid={'read_only':True,'quality_verified':False,'audited':True,
                 'audit':{'identity':'0'*64,'quality_verified':False}}
        with patch('vision_rsi.baseline_observe.job_request',return_value={'status':'running','spec_hash':digest(self.record['spec'])}), \
             patch('vision_rsi.baseline_observe.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(invalid),stderr='')):
            with self.assertRaises(ValueError):observe(self.record,True)
