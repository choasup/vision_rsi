import unittest
from unittest.mock import patch

from vision_rsi.candidate_runtime import validate_runtime_identity, run
from vision_rsi.runner import digest


def identity():
    return {'protocol':'vision-rsi/selected-cpu-runtime/v1','python_binary_sha256':'a'*64,
            'bwrap_binary_sha256':'b'*64,'bwrap_path':'/usr/bin/bwrap','kernel_release':'fixture-kernel',
            'machine':'fixture-machine','controller_python':'fixture-python'}


class CandidateRuntimeTests(unittest.TestCase):
    def test_schema_and_content_hash_refuse_changed_identity(self):
        value=identity();checksum=digest(value)
        self.assertTrue(validate_runtime_identity(value,checksum))
        value['kernel_release']='changed'
        with self.assertRaisesRegex(ValueError,'hash or path differs'):validate_runtime_identity(value,checksum)
        value['extra']='unbounded'
        with self.assertRaisesRegex(ValueError,'Invalid selected'):validate_runtime_identity(value,digest(value))

    @patch('vision_rsi.candidate_runtime.subprocess.Popen')
    def test_drift_blocks_before_any_candidate_process(self,process):
        value=identity()
        with patch('vision_rsi.candidate_runtime.runtime_identity',return_value=(value,digest(value))):
            with self.assertRaisesRegex(ValueError,'candidate was not executed'):
                run({'workspace':'/owned-fixture','expected_runtime_identity_sha256':'0'*64})
        process.assert_not_called()
