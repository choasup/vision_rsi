import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from vision_rsi.detector import COCO_IDS
from vision_rsi.resource_equivalence import verify
from vision_rsi.resource_verify import verify_images


class EquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)/'dataset'
        (cls.root/'val2017').mkdir(parents=True);(cls.root/'annotations').mkdir()
        stream=io.BytesIO();Image.new('RGB',(2,3),(10,20,30)).save(stream,format='JPEG')
        cls.image_bytes=stream.getvalue()
        images=[]
        for i in range(5000):
            name=f'{i:012d}.jpg';(cls.root/'val2017'/name).write_bytes(cls.image_bytes)
            images.append({'id':i,'file_name':name,'width':2,'height':3})
        cls.annotation=cls.root/'annotations/instances_val2017.json'
        cls.annotation.write_text(json.dumps({'categories':[{'id':i} for i in COCO_IDS],
                                             'images':images,'annotations':[]}),encoding='utf-8')
        cls.reference=verify_images(cls.root,'val',5000)
        cls.receipt=Path(cls.temp.name)/'reference.json'
        cls.receipt.write_text(json.dumps(cls.reference),encoding='utf-8')
        cls.sha=hashlib.sha256(cls.receipt.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_all_5000_decoded_reference_bytes_match_without_claiming_second_decode(self):
        progress=[]
        result=verify(self.root,self.receipt,self.sha,progress.append)
        self.assertEqual(result['images'],5000)
        self.assertTrue(result['byte_equivalence_verified'])
        self.assertTrue(result['reference_pixel_decode_verified'])
        self.assertFalse(result['pixel_decode_verified'])
        self.assertFalse(result['dataset_ready']);self.assertFalse(result['coco_evaluated'])
        self.assertEqual(result['image_manifest_sha256'],self.reference['image_manifest_sha256'])
        self.assertEqual(progress[-1]['status'],'completed')

    def test_changed_image_or_annotations_cannot_reuse_the_reference(self):
        path=self.root/'val2017/000000000000.jpg'
        changed=io.BytesIO();Image.new('RGB',(2,3),(200,20,30)).save(changed,format='JPEG')
        progress=[]
        try:
            path.write_bytes(changed.getvalue())
            with self.assertRaisesRegex(ValueError,'bytes differ'):verify(self.root,self.receipt,self.sha,progress.append)
            self.assertFalse(any(row['byte_equivalence_verified'] for row in progress))
        finally:path.write_bytes(self.image_bytes)
        original=self.annotation.read_bytes()
        try:
            self.annotation.write_bytes(original+b'\n')
            with self.assertRaisesRegex(ValueError,'annotations differ'):verify(self.root,self.receipt,self.sha)
        finally:self.annotation.write_bytes(original)

    def test_partial_unpinned_or_non_decode_receipts_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'SHA-256 differs'):verify(self.root,self.receipt,'0'*64)
        with self.assertRaisesRegex(ValueError,'Pinned reference'):verify(self.root,self.receipt,'bad')
        for change in ({'images':1},{'pixel_decode_verified':False},{'gpu_used':True},
                       {'training_started':True},{'image_bytes':True},{'image_manifest_sha256':'bad'}):
            bad=Path(self.temp.name)/'bad.json'
            bad.write_text(json.dumps(dict(copy.deepcopy(self.reference),**change)),encoding='utf-8')
            sha=hashlib.sha256(bad.read_bytes()).hexdigest()
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'full-split CPU pixel verification'):
                verify(self.root,bad,sha)
