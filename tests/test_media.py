import base64
import json
from pathlib import Path
import tempfile
import unittest
from vision_rsi.media import image_request


class MediaTransportTests(unittest.TestCase):
    def setUp(self):
        self.contract={'inputs':{'image':{'type':'image','required':True}}}
    def test_relative_path_and_file_uri_preserve_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'an%20 image.jpg';image.write_bytes(b'fixture-image-bytes')
            path=root/'input.json'
            for uri in ['an%20 image.jpg',image.as_uri()]:
                path.write_text(json.dumps({'sample_id':'one','inputs':{'image':{'type':'image','uri':uri}}}))
                request=image_request(self.contract,path)
                self.assertEqual(base64.b64decode(request['image_base64']),image.read_bytes())
    def test_network_and_missing_media_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.json'
            for uri in ['https://example.com/image.jpg','file://server/share/image.jpg','missing.jpg']:
                path.write_text(json.dumps({'sample_id':'one','inputs':{'image':{'type':'image','uri':uri}}}))
                with self.assertRaises(ValueError):image_request(self.contract,path)
    def test_joint_images_are_not_silently_split(self):
        contract={'inputs':{'images':{'type':'image_list','required':True,'min_items':2,'max_items':2,'semantics':'joint'}}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.json'
            path.write_text(json.dumps({'sample_id':'one','inputs':{'images':{'type':'image_list','items':[{'uri':'one.jpg'},{'uri':'two.jpg'}]}}}))
            with self.assertRaisesRegex(ValueError,'joint images/video'):image_request(contract,path)

class DirectImageTests(unittest.TestCase):
    def test_single_image_path_is_wrapped_from_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'photo.png';path.write_bytes(b'fixture')
            request=image_request({'inputs':{'photo':{'type':'image','required':True}}},path)
            self.assertEqual(request['sample']['sample_id'],'photo')
            self.assertEqual(request['sample']['inputs']['photo']['uri'],str(path.resolve()))
