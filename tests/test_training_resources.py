from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple

from vision_rsi.training_resources import step, TRAIN_RESOURCE


class TrainingResourceTests(unittest.TestCase):
    def test_checksum_deadline_retains_archive_without_success_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            part=Path(tmp)/'train2017.zip.part'
            part.write_bytes(b'partial fixture')
            with patch('vision_rsi.training_resources.shutil.disk_usage',return_value=namedtuple('Disk','free')(100_000_000_000)), \
                 patch('vision_rsi.training_resources.download',side_effect=TimeoutError('verification deadline')):
                result=step(tmp,240)
            self.assertEqual(result['resource']['status'],'verification_pending')
            self.assertFalse(result['resource']['sha256_verified'])
            self.assertFalse(result['dataset_ready'])
            self.assertEqual(part.read_bytes(),b'partial fixture')
            self.assertFalse((Path(tmp)/'train2017.zip').exists())

    def test_disk_admission_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('vision_rsi.training_resources.shutil.disk_usage',return_value=namedtuple('Disk','free')(1)), \
                 patch('vision_rsi.training_resources.download') as download:
                with self.assertRaises(ValueError):step(tmp,240)
                download.assert_not_called()

    def test_bounded_official_download_never_claims_training_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('vision_rsi.training_resources.shutil.disk_usage',return_value=namedtuple('Disk','free')(100_000_000_000)), \
                 patch('vision_rsi.training_resources.download',return_value={'status':'downloaded'}) as download:
                result=step(tmp,240)
                self.assertFalse(result['dataset_ready']);self.assertFalse(result['training_started'])
                self.assertFalse(result['gpu_used'])
                self.assertEqual(download.call_args.args[0],TRAIN_RESOURCE)
                for seconds in (True,0,241):
                    with self.assertRaises(ValueError):step(tmp,seconds)
