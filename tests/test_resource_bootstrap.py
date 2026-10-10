import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.resource_bootstrap import download


class Response:
    def __init__(self,asset,data,status=200,offset=0,clock=None):
        self.asset=asset;self.data=io.BytesIO(data);self.status=status;self.clock=clock
        self.headers={'ETag':asset['etag'],'Content-Length':str(len(data))}
        if status==206:self.headers['Content-Range']=f"bytes {offset}-{asset['bytes']-1}/{asset['bytes']}"
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def geturl(self):return self.asset['url']
    def read1(self,size):
        if self.clock is not None:self.clock[0]+=1
        return self.data.read(min(3,size))


class ResourceBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=b'0123456789'
        self.asset={'name':'fixture.bin','url':'https://download.pytorch.org/models/fixture.bin','bytes':10,'etag':'"fixture"'}
    def test_deadline_resume_and_completed_content_tamper(self):
        clock=[0]
        with patch('vision_rsi.resource_bootstrap.time.monotonic',side_effect=lambda:clock[0]):
            first=download(self.asset,self.root,2,lambda *a,**k:Response(self.asset,self.data,clock=clock))
            self.assertEqual(first['status'],'partial');self.assertEqual(first['downloaded_bytes'],6)
            calls=[]
            def resume(request,**kwargs):
                calls.append(dict(request.header_items()))
                return Response(self.asset,self.data[6:],206,6)
            second=download(self.asset,self.root,100,resume)
            self.assertEqual(second['sha256'],hashlib.sha256(self.data).hexdigest())
            self.assertEqual(calls[0]['Range'],'bytes=6-')
            self.assertTrue(download(self.asset,self.root,100,resume)['reused']);self.assertEqual(len(calls),1)
            (self.root/'fixture.bin').write_bytes(b'XXXXXXXXXX')
            with self.assertRaisesRegex(ValueError,'changed'):download(self.asset,self.root,100,resume)
    def test_ignored_range_does_not_corrupt_partial_bytes(self):
        clock=[0]
        with patch('vision_rsi.resource_bootstrap.time.monotonic',side_effect=lambda:clock[0]):
            download(self.asset,self.root,1,lambda *a,**k:Response(self.asset,self.data,clock=clock))
            part=self.root/'fixture.bin.part';before=part.read_bytes()
            with self.assertRaisesRegex(ValueError,'resume range'):
                download(self.asset,self.root,100,lambda *a,**k:Response(self.asset,self.data))
            self.assertEqual(part.read_bytes(),before);self.assertFalse((self.root/'fixture.bin').exists())
    def test_untracked_and_changed_source_refused(self):
        (self.root/'fixture.bin').write_bytes(self.data)
        with self.assertRaisesRegex(ValueError,'Untracked'):download(self.asset,self.root,100)
        (self.root/'fixture.bin').unlink()
        with patch('vision_rsi.resource_bootstrap.time.monotonic',return_value=0):
            download(self.asset,self.root,100,lambda *a,**k:Response(self.asset,self.data))
            changed=dict(self.asset,etag='"changed"')
            with self.assertRaisesRegex(ValueError,'source identity'):download(changed,self.root,100)
    def test_verified_rename_crash_window_preserves_digest(self):
        with patch('vision_rsi.resource_bootstrap.time.monotonic',return_value=0):
            download(self.asset,self.root,100,lambda *a,**k:Response(self.asset,self.data))
            final=self.root/'fixture.bin';part=self.root/'fixture.bin.part';final.rename(part)
            recovered=download(self.asset,self.root,100)
            self.assertEqual(recovered['sha256'],hashlib.sha256(self.data).hexdigest())
            final.rename(part);part.write_bytes(b'XXXXXXXXXX')
            with self.assertRaisesRegex(ValueError,'Previously verified'):download(self.asset,self.root,100)
