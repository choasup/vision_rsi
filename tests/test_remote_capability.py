import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.capability import Capabilities
from vision_rsi.runner import digest
from test_acceptance import evidence,wrap


class RemoteCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry=Capabilities(self.root/'registry');self.addCleanup(self.registry.close)
        frozen,self.receipt=evidence()
        frozen['task_id']='coco-task'
        frozen['contract']['inputs']={'image':{'type':'image','required':True}}
        frozen['contract']['output_schema']={'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}},'required':['detections']}
        self.plan=self.root/'plan.json';self.plan.write_text(json.dumps(frozen))
        self.receipt['run_id']='train-'+'a'*32
        receipt_path=self.root/'receipt.json';receipt_path.write_text(json.dumps(self.receipt))
        self.record={'status':'completed','run_id':self.receipt['run_id'],'session_id':'fixture','plan_id':digest(frozen),
                     'remote':{'ssh_host':'fixture','workspace':'/workspace'},
                     'details':{'plan_path':str(self.plan),'receipt_path':str(receipt_path),'deployment':{'directory':'/workspace/releases/frozen'},'output_directory':'/workspace/training/task/'+self.receipt['run_id']}}
        self.image=self.root/'image.jpg';self.image.write_bytes(b'unit-test-image; remote inference is mocked')
        self.sample=self.root/'sample.json';self.sample.write_text(json.dumps({'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.jpg'}}}))
    @staticmethod
    def response(remote,request,source_path):
        return {'sample_id':request['sample']['sample_id'],'output':{'detections':[]},'device':'cpu',
                'image_sha256':hashlib.sha256(base64.b64decode(request['image_base64'])).hexdigest(),
                'checkpoint_sha256':request['checkpoint_sha256'],'training_identity_hash':request['training_identity_hash']}
    @patch('vision_rsi.remote.infer_training',side_effect=response)
    def test_register_then_test_uses_pinned_adapter_and_media(self,infer):
        manifest=self.registry.register_training(self.record,self.sample)
        self.assertEqual(manifest['status'],'validated')
        result=self.registry.infer('coco-task',self.sample)
        self.assertEqual(result['output'],{'detections':[]});self.assertEqual(infer.call_count,2)
        before=self.registry.input_fingerprint('coco-task',self.sample)
        self.image.write_bytes(b'changed media with identical JSON')
        self.assertNotEqual(before,self.registry.input_fingerprint('coco-task',self.sample))
        with self.assertRaisesRegex(ValueError,'changed after batch snapshot'):
            self.registry.infer('coco-task',self.sample,expected_input_fingerprint=before)
        self.assertEqual(infer.call_count,2)
        (self.registry.root/'coco-task'/manifest['version']/'inference.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'integrity'):self.registry.infer('coco-task',self.sample)
    @patch('vision_rsi.remote.infer_training')
    def test_not_met_refuses_registration_before_backend(self,infer):
        plan,receipt=evidence(20)
        self.plan.write_text(json.dumps(dict(plan,task_id='coco-task')))
        self.record['plan_id']=digest(dict(plan,task_id='coco-task'))
        receipt['run_id']=self.record['run_id']
        Path(self.record['details']['receipt_path']).write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'not met'):self.registry.register_training(self.record,self.sample)
        infer.assert_not_called();self.assertEqual(self.registry.list(),[])
    @patch('vision_rsi.remote.infer_training')
    def test_wrong_image_response_never_registers(self,infer):
        infer.return_value={'sample_id':'one','checkpoint_sha256':'c'*64,'training_identity_hash':json.loads(base64.b64decode(self.receipt['reports']['result.json']['base64']))['identity_hash'],'image_sha256':'0'*64,'output':{'detections':[]},'device':'cpu'}
        with self.assertRaisesRegex(ValueError,'image bytes differ'):self.registry.register_training(self.record,self.sample)
        self.assertEqual(self.registry.list(),[])

    @patch('vision_rsi.remote.infer_training',side_effect=response)
    def test_batch_images_preserve_ids_and_detect_changed_pixels(self,infer):
        from vision_rsi.batch import batch,input_rows
        self.registry.register_training(self.record,self.sample)
        images=self.root/'images';images.mkdir();image=images/'photo.jpg';image.write_bytes(b'first-image')
        rows=input_rows(input_dir=images)
        output=self.root/'batch-output'
        result=batch(self.registry,'coco-task',rows,output)
        self.assertEqual(result['succeeded'],1)
        state=json.loads((output/'batch-state.json').read_text())
        files=[p for p in output.glob('*.json') if p.name not in ('batch-state.json','summary.json')]
        item=json.loads(files[0].read_text())
        self.assertEqual(item['sample_id'],'photo.jpg')
        image.write_bytes(b'changed-image-same-name')
        with self.assertRaisesRegex(ValueError,'Sample content changed'):
            batch(self.registry,'coco-task',rows,output,resume=True)
