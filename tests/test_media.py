import base64
import json
from pathlib import Path
import tempfile
import unittest
from vision_rsi.media import image_request,sample_request,verify_sample_request


class JointMediaTransportTests(unittest.TestCase):
    def test_joint_sample_keeps_order_text_video_policy_and_content_identity(self):
        contract={'inputs':{'views':{'type':'image_list','required':True,'min_items':2,'max_items':2,'semantics':'joint'},
                            'clip':{'type':'video','required':True,'processing':{'sampling':'2 fps','temporal':'ordered','audio':'ignore'}},
                            'question':{'type':'text','required':True}}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,data in [('left.jpg',b'left'),('right.jpg',b'right'),('clip.mp4',b'video-fixture')]:
                (root/name).write_bytes(data)
            sample={'sample_id':'joint-one','inputs':{'views':{'type':'image_list','items':[{'uri':'left.jpg'},{'uri':'right.jpg'}]},
                    'clip':{'type':'video','uri':'clip.mp4'},'question':{'type':'text','value':'Compare the views and clip'}}}
            path=root/'sample.json';path.write_text(json.dumps(sample))
            packet=sample_request(contract,path)
            self.assertEqual(packet['sample'],sample)
            self.assertEqual([(a['field'],a['index']) for a in packet['assets']],[('views',0),('views',1),('clip',0)])
            self.assertEqual([base64.b64decode(a['content_base64']) for a in packet['assets']],[b'left',b'right',b'video-fixture'])
            self.assertEqual(packet['video_processing']['clip'],contract['inputs']['clip']['processing'])
            self.assertFalse(packet['media_decoded']);self.assertFalse(packet['inference_performed'])
            self.assertEqual(verify_sample_request(contract,packet)['sample_id'],'joint-one')
            reordered=json.loads(json.dumps(packet,sort_keys=True))
            self.assertTrue(verify_sample_request(contract,reordered)['valid'])
            mutations=[lambda p:p['assets'].reverse(),lambda p:p['assets'].pop(),
                       lambda p:p['assets'][0].update(content_base64=base64.b64encode(b'fake').decode()),
                       lambda p:p['assets'][0].update(index=True),lambda p:p.update(content_bytes=True),
                       lambda p:p['video_processing']['clip'].update(sampling='99 fps'),
                       lambda p:p['sample']['inputs']['question'].update(value='changed question'),
                       lambda p:p.update(media_decoded=True),lambda p:p.update(input_fingerprint='0'*64)]
            for mutate in mutations:
                changed_packet=json.loads(json.dumps(packet));mutate(changed_packet)
                with self.assertRaises(ValueError):verify_sample_request(contract,changed_packet)
            self.assertEqual(sample_request(contract,path)['input_fingerprint'],packet['input_fingerprint'])
            (root/'right.jpg').write_bytes(b'changed')
            self.assertNotEqual(sample_request(contract,path)['input_fingerprint'],packet['input_fingerprint'])
            changed=json.loads(json.dumps(contract));changed['inputs']['clip']['processing']['sampling']='1 fps'
            self.assertNotEqual(sample_request(changed,path)['input_fingerprint'],sample_request(contract,path)['input_fingerprint'])
            for media in root.glob('*.jpg'):media.unlink()
            (root/'clip.mp4').unlink()
            # Receiving only the packet must not consult sender filesystem paths.
            self.assertTrue(verify_sample_request(contract,packet)['valid'])

    def test_unreadable_remote_empty_and_oversized_media_fail_before_packet(self):
        contract={'inputs':{'photo':{'type':'image','required':True}}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'sample.json';media=root/'photo.jpg'
            media.write_bytes(b'')
            for uri in ('https://example.com/image.jpg','file:///photo.jpg?query=x','missing.jpg','photo.jpg'):
                path.write_text(json.dumps({'sample_id':'one','inputs':{'photo':{'type':'image','uri':uri}}}))
                with self.subTest(uri=uri),self.assertRaises((ValueError,OSError)):sample_request(contract,path)
            with media.open('wb') as stream:stream.truncate(20*1024*1024+1)
            with self.assertRaisesRegex(ValueError,'per-file limit'):sample_request(contract,path)


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
