import hashlib
import stat
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

    def test_crc_corruption_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'a.zip'; dest = root / 'data'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
                z.writestr('a.jpg', b'unique-payload')
            content = archive.read_bytes().replace(b'unique-payload', b'broken-payload')
            archive.write_bytes(content)
            with self.assertRaises(zipfile.BadZipFile):
                extract(archive, dest, hashlib.sha256(content).hexdigest(), max_bytes=100, max_files=2)
            self.assertFalse(dest.exists())
            self.assertEqual(list(root.glob('.extract-*')), [])

    def test_special_files_and_reserved_receipt_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, (name, mode) in enumerate((('.', 0), ('.extraction-receipt.json', 0),
                                                ('link', stat.S_IFLNK), ('fifo', stat.S_IFIFO))):
                archive = root / f'{index}.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    info = zipfile.ZipInfo(name); info.create_system = 3
                    info.external_attr = (mode | 0o644) << 16
                    z.writestr(info, b'payload')
                with self.assertRaises(ValueError):
                    extract(archive, root / f'd{index}', hashlib.sha256(archive.read_bytes()).hexdigest(),
                            max_bytes=100, max_files=2)
