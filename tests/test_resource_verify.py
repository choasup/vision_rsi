import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from vision_rsi.detector import COCO_IDS
from vision_rsi.resource_verify import verify_images


class VerifyTests(unittest.TestCase):
    def test_actual_pixels_dimensions_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'annotations').mkdir();(root/'val2017').mkdir()
            path=root/'val2017/a.jpg'
            Image.new('RGB',(10,12),(100,50,0)).save(path)
            data={'categories':[{'id':i} for i in COCO_IDS],
                  'images':[{'id':1,'file_name':'a.jpg','width':10,'height':12}],
                  'annotations':[]}
            annotation=root/'annotations/instances_val2017.json';annotation.write_text(json.dumps(data))
            progress=[]
            first=verify_images(root,'val',1,progress.append)
            self.assertEqual([r['status'] for r in progress],['checking_coverage','decoding_images','completed'])
            self.assertEqual(progress[-1]['decoded_images'],1)
            self.assertTrue(progress[-1]['verification_complete'])
            self.assertTrue(all(not r['dataset_ready'] and not r['gpu_used'] for r in progress))
            self.assertTrue(first['pixel_decode_verified']);self.assertFalse(first['coco_evaluated'])
            self.assertEqual(first,verify_images(root,'val',1))
            Image.new('RGB',(10,12),(100,50,0)).save(path,format='PNG')
            png=verify_images(root,'val',1)
            self.assertEqual(png['formats'],{'PNG':1})
            self.assertTrue(png['pixel_decode_verified'])
            self.assertNotEqual(first['image_manifest_sha256'],png['image_manifest_sha256'])
            Image.new('RGB',(10,12),(100,50,0)).save(path,format='BMP')
            with self.assertRaisesRegex(ValueError,'image 1 a.jpg, BMP'):verify_images(root,'val',1)
            Image.new('RGB',(10,12),(100,50,0)).save(path,format='PNG',save_all=True,
                append_images=[Image.new('RGB',(10,12),(0,50,100))],duration=100,loop=0)
            with self.assertRaisesRegex(ValueError,'Unexpected image format'):verify_images(root,'val',1)
            Image.new('RGB',(10,12),(0,50,100)).save(path)
            self.assertNotEqual(first['image_manifest_sha256'],verify_images(root,'val',1)['image_manifest_sha256'])
            data['images'][0]['height']=13;annotation.write_text(json.dumps(data))
            with self.assertRaises(ValueError):verify_images(root,'val',1)
            data['images'][0]['height']=12;annotation.write_text(json.dumps(data))
            path.write_bytes(b'not-a-jpeg')
            failed=[]
            with self.assertRaises(OSError):verify_images(root,'val',1,failed.append)
            self.assertFalse(any(r['verification_complete'] for r in failed))
