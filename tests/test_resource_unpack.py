import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from vision_rsi.campaign import lease
from vision_rsi.resource_unpack import Deadline,step


class ResumableUnpackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=self.root/'archive.zip';self.dest=self.root/'data'
        with zipfile.ZipFile(self.archive,'w') as bundle:
            for name in ('a','b','c'):bundle.writestr('images/'+name,b'payload-'+name.encode())
        self.sha=hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def run_step(self,**kwargs):
        return step(self.archive,self.dest,self.sha,max_bytes=100,max_files=4,**kwargs)

    def test_partial_steps_do_not_publish_and_complete_is_idempotent(self):
        for count in (1,2):
            result=self.run_step(max_new_files=1)
            self.assertEqual(result['completed_entries'],count);self.assertEqual(result['status'],'partial')
            self.assertFalse(self.dest.exists())
        result=self.run_step(max_new_files=1)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['extraction']['files'],3)
        self.assertTrue(result['extraction']['crc_verified']);self.assertFalse(result['dataset_ready'])
        self.assertEqual(self.run_step()['extraction'],result['extraction'])
        for name in ('a','b','c'):self.assertEqual((self.dest/'images'/name).read_bytes(),b'payload-'+name.encode())

    def test_process_failure_after_file_publication_recovers_orphan_without_merge(self):
        rename=Path.rename;failed=[]
        def fail_after(path,target):
            result=rename(path,target)
            if path.name=='pending.bin' and not failed:
                failed.append(True);raise OSError('simulated death after file rename before journal commit')
            return result
        with patch.object(Path,'rename',fail_after),self.assertRaises(OSError):self.run_step()
        self.assertFalse(self.dest.exists())
        result=self.run_step();self.assertEqual(result['status'],'completed')
        self.assertEqual(result['extraction']['files'],3)

    def test_process_failure_after_directory_publication_recovers_finalization(self):
        rename=Path.rename
        def fail_after(path,target):
            result=rename(path,target)
            if path.name=='payload':raise OSError('simulated death before final journal commit')
            return result
        with patch.object(Path,'rename',fail_after),self.assertRaises(OSError):self.run_step()
        self.assertTrue(self.dest.exists())
        self.assertEqual(self.run_step()['status'],'completed')

    def test_changed_saved_bytes_archive_or_limits_refuse_resume(self):
        self.run_step(max_new_files=1)
        saved=self.root/'data.unpack/payload/images/a';saved.write_bytes(b'changed-a')
        with self.assertRaisesRegex(ValueError,'Saved extraction file changed'):self.run_step()
        saved.write_bytes(b'payload-a')
        with self.assertRaisesRegex(ValueError,'identity changed'):
            step(self.archive,self.dest,self.sha,max_bytes=101,max_files=4)
        self.archive.write_bytes(self.archive.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):self.run_step()
        self.assertFalse(self.dest.exists())

    def test_deadline_and_active_lease_do_not_publish(self):
        with patch('vision_rsi.resource_unpack.checksum',side_effect=Deadline()):
            result=self.run_step()
        self.assertEqual(result['status'],'partial');self.assertTrue(result['deadline_reached'])
        self.assertFalse(self.dest.exists());self.assertFalse((self.root/'data.unpack').exists())
        self.run_step(max_new_files=1)
        with lease(self.root/'data.unpack/unpack.lock'),self.assertRaises(RuntimeError):self.run_step()
        self.assertFalse(self.dest.exists())

    def test_bad_crc_unsafe_members_and_existing_destination_never_promote(self):
        self.dest.mkdir();(self.dest/'keep').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'merge'):self.run_step()
        self.assertEqual((self.dest/'keep').read_bytes(),b'original')
        for index,name in enumerate(('../escape','/absolute','a\\b','.extraction-receipt.json','a//b')):
            archive=self.root/f'bad{index}.zip'
            with zipfile.ZipFile(archive,'w') as z:
                info=zipfile.ZipInfo('placeholder');info.filename=name;z.writestr(info,b'fixture')
            with self.assertRaises(ValueError):step(archive,self.root/f'bad{index}',hashlib.sha256(archive.read_bytes()).hexdigest())
        raw=self.archive.read_bytes().replace(b'payload-a',b'broken--a');self.archive.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):
            step(self.archive,self.root/'corrupt',hashlib.sha256(raw).hexdigest())
        self.assertFalse((self.root/'corrupt').exists())

    def test_pending_file_is_private_and_changed_published_bytes_are_rejected(self):
        self.run_step(max_new_files=1)
        pending=self.root/'data.unpack/pending.bin';pending.write_bytes(b'interrupted write')
        self.assertEqual(self.run_step()['status'],'completed')
        published=self.dest/'images/a';published.write_bytes(b'changed-a')
        with self.assertRaisesRegex(ValueError,'Saved extraction file changed'):self.run_step()
