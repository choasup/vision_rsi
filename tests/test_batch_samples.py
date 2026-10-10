import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.batch import batch,input_rows,sample_file
from vision_rsi.media import image_request


class ContractFixtureRegistry:
    contract={'inputs':{'image':{'type':'image','required':True}}}
    def __init__(self):self.calls=[]
    def resolve_version(self,task,version):return version or 'fixture-v1'
    def input_fingerprint(self,task,path,version):return image_request(self.contract,path)['input_fingerprint']
    def infer(self,task,path,version,expected_input_fingerprint=None,sample_id=None):
        request=image_request(self.contract,path)
        if request['input_fingerprint']!=expected_input_fingerprint:raise ValueError('Input changed before dispatch')
        self.calls.append(request['sample'])
        return {'output':{'fixture_only':True},'acceptance':{'fixture':True}}


class BatchSampleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.image=self.root/'image.bin';self.image.write_bytes(b'fixture image bytes, not a learned model')
        self.sample={'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.bin'}}}
        self.manifest=self.root/'samples.jsonl';self.registry=ContractFixtureRegistry()

    def test_inline_and_legacy_samples_share_one_frozen_version(self):
        (self.root/'legacy.json').write_text(json.dumps(dict(self.sample,sample_id='two')))
        self.manifest.write_text(json.dumps(self.sample)+'\n'+json.dumps({'sample_id':'two','input':'legacy.json'}))
        rows=input_rows(manifest=self.manifest);result=batch(self.registry,'fixture',rows,self.root/'output')
        self.assertEqual(result['succeeded'],2);self.assertEqual(result['capability_version'],'fixture-v1')
        self.assertEqual(self.registry.calls[0]['inputs']['image']['uri'],str(self.image.resolve()))
        self.assertEqual(len(list((self.root/'output/input-samples').glob('*.json'))),1)
        self.assertEqual(json.loads(self.manifest.read_text().splitlines()[0]),self.sample)
        self.registry.calls.clear();batch(self.registry,'fixture',rows,self.root/'output',resume=True)
        self.assertEqual(self.registry.calls,[])

    def test_changed_media_and_snapshot_stop_resume_before_dispatch(self):
        self.manifest.write_text(json.dumps(self.sample));rows=input_rows(manifest=self.manifest)
        batch(self.registry,'fixture',rows,self.root/'output');self.registry.calls.clear()
        original=self.image.read_bytes();self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'content changed'):batch(self.registry,'fixture',rows,self.root/'output',resume=True)
        self.assertEqual(self.registry.calls,[]);self.image.write_bytes(original)
        snapshot=next((self.root/'output/input-samples').glob('*.json'));snapshot.write_text('{}')
        with self.assertRaisesRegex(ValueError,'content changed'):batch(self.registry,'fixture',rows,self.root/'output',resume=True)
        self.assertEqual(self.registry.calls,[])

    def test_joint_images_and_video_stay_one_sample_and_keep_policy(self):
        sample={'sample_id':'joint','inputs':{'views':{'type':'image_list','items':[{'uri':'image.bin'},{'uri':'image.bin'}]},
            'clip':{'type':'video','uri':'video.bin'},'text':{'type':'text','value':'提示'}}}
        row={'sample_id':'joint','sample':sample,'media_base':str(self.root)}
        output=self.root/'output';output.mkdir();value=json.loads(Path(sample_file(row,output)).read_text())
        self.assertEqual(value['sample_id'],'joint');self.assertEqual(len(value['inputs']['views']['items']),2)
        self.assertEqual(value['inputs']['clip']['uri'],str((self.root/'video.bin').resolve()))
        self.assertEqual(value['inputs']['text'],sample['inputs']['text'])

    def test_ambiguous_format_is_a_failure_not_silent_override(self):
        self.manifest.write_text(json.dumps(dict(self.sample,input='legacy.json')))
        rows=input_rows(manifest=self.manifest);result=batch(self.registry,'fixture',rows,self.root/'output')
        self.assertEqual(result['failed'],1);self.assertEqual(self.registry.calls,[])
