from types import SimpleNamespace as N
import subprocess
import unittest
from unittest.mock import patch
from vision_rsi.training_runtime import fingerprint
from vision_rsi.runner import digest


class TrainingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.props=N(name='fixture H20',major=9,minor=0,total_memory=100)
        self.cudnn=N(version=lambda:90100,benchmark=False,deterministic=True,allow_tf32=False)
        self.torch=N(cuda=N(get_device_properties=lambda device:self.props,nccl=N(version=lambda:(2,21,5))),
                     backends=N(cudnn=self.cudnn,cuda=N(matmul=N(allow_tf32=False))),version=N(cuda='12.4'),
                     __config__=N(show=lambda:'fixture build'),are_deterministic_algorithms_enabled=lambda:True)

    @patch('vision_rsi.training_runtime.importlib.metadata.version',return_value='fixture')
    @patch('vision_rsi.training_runtime.subprocess.run')
    def test_stable_identity_detects_driver_library_and_device_changes(self,run,version):
        run.return_value=N(stdout='550.1\n550.1\n')
        first=fingerprint(self.torch,0)
        self.assertEqual(first,fingerprint(self.torch,7))
        self.assertEqual(first['driver_versions'],['550.1'])
        self.assertEqual(run.call_args.kwargs['timeout'],10)
        run.return_value=N(stdout='550.2\n')
        self.assertNotEqual(digest(first),digest(fingerprint(self.torch,0)))
        run.return_value=N(stdout='550.1\n')
        version.return_value='changed'
        self.assertNotEqual(digest(first),digest(fingerprint(self.torch,0)))
        version.return_value='fixture'
        self.torch.cuda.nccl.version=lambda:(2,21,5,'fixture-suffix')
        self.assertEqual(fingerprint(self.torch,0)['nccl'],[2,21,5,'fixture-suffix'])
        self.torch.cuda.nccl.version=lambda:(2,21,5)
        version.return_value='fixture';self.props.major=8
        self.assertNotEqual(digest(first),digest(fingerprint(self.torch,0)))

    @patch('vision_rsi.training_runtime.importlib.metadata.version',return_value='fixture')
    @patch('vision_rsi.training_runtime.subprocess.run')
    def test_missing_environment_evidence_never_becomes_empty_identity(self,run,version):
        for text in ('','unavailable','550.1\nunknown'):
            run.return_value=N(stdout=text)
            with self.assertRaisesRegex(ValueError,'driver version'):fingerprint(self.torch,0)
        run.side_effect=subprocess.TimeoutExpired('nvidia-smi',10)
        with self.assertRaises(subprocess.TimeoutExpired):fingerprint(self.torch,0)
        run.side_effect=None;run.return_value=N(stdout='550.1')
        self.cudnn.version=lambda:None
        with self.assertRaisesRegex(ValueError,'Incomplete'):fingerprint(self.torch,0)
