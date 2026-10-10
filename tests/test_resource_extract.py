import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from vision_rsi.resource_extract import extract


class ExtractTests(unittest.TestCase):
    def test_verified_extraction_and_refuse_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'a.zip'; dest = root / 'data'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('val2017/a.jpg', b'fixture')
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            result = extract(archive, dest, sha, max_bytes=100, max_files=2)
            self.assertTrue(result['crc_verified'])
            self.assertFalse(result['dataset_coverage_verified'])
            self.assertEqual((dest / 'val2017/a.jpg').read_bytes(), b'fixture')
            with self.assertRaises(ValueError):
                extract(archive, dest, sha, max_bytes=100, max_files=2)

    def test_bad_hash_paths_and_limits_leave_no_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, name in enumerate(('../escape', '/absolute', 'a\\b', 'a/../b', 'a//b', 'safe')):
                archive = root / f'{index}.zip'; dest = root / f'd{index}'
                with zipfile.ZipFile(archive, 'w') as z:
                    info = zipfile.ZipInfo('placeholder')
                    info.filename = name
                    z.writestr(info, b'fixture')
                sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    extract(archive, dest, sha, max_bytes=1 if name == 'safe' else 100, max_files=2)
                self.assertFalse(dest.exists())
            with self.assertRaises(ValueError):
                extract(archive, dest, '0' * 64, max_bytes=100, max_files=2)
