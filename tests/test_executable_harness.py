import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.harness import build
from vision_rsi.executable_harness import build_executable


class ExecutableHarnessTests(unittest.TestCase):
    def test_standalone_joint_media_packet_preserves_sample_and_rejects_overwrite(self):
        sample=json.loads(json.dumps(self.session['versions'][-1]['contract']['example_input']))
        for value in sample['inputs'].values():
            for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                name=f"{value['type']}-{index}.bin"
                (self.root/name).write_bytes(name.encode())
                item['uri']=name
        path=self.root/'sample.json';path.write_text(json.dumps(sample))
        output=self.root/'packet.json'
        result=self.run_harness('prepare-input','--input',str(path),'--output',str(output))
        self.assertEqual(result.returncode,0,result.stderr)
        packet=json.loads(output.read_text())
        self.assertEqual(packet['sample'],sample)
        self.assertEqual(len(packet['assets']),3)
        self.assertFalse(json.loads(result.stdout)['inference_performed'])
        verified=self.run_harness('verify-input','--input',str(output))
        self.assertEqual(verified.returncode,0,verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['input_fingerprint'],packet['input_fingerprint'])
        tampered=json.loads(json.dumps(packet));tampered['assets'][0]['sha256']='0'*64
        corrupted=self.root/'tampered.json';corrupted.write_text(json.dumps(tampered))
        rejected=self.run_harness('verify-input','--input',str(corrupted))
        self.assertNotEqual(rejected.returncode,0);self.assertIn('hash',rejected.stderr)
        original=output.read_bytes()
        result=self.run_harness('prepare-input','--input',str(path),'--output',str(output))
        self.assertNotEqual(result.returncode,0);self.assertIn('already exists',result.stderr)
        self.assertEqual(output.read_bytes(),original)
        result=self.run_harness('prepare-input','--input',str(path),'--output',str(self.folder/'extra.json'))
        self.assertNotEqual(result.returncode,0);self.assertIn('frozen harness',result.stderr)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.storage={key:str(self.root/key) for key in ('sessions','runs','campaigns','registry','plans')}
        self.store=Sessions(self.storage['sessions'])
        session=self.store.create('inspection','Joint images and video inspection')
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        self.session=self.store.define(session['session_id'],contract)
        self.config={'remote':{'ssh_host':'fixture','workspace':'/workspace','coco_root':''},
                     'llm':{'model':'fixture','base_url':'https://fixture.invalid','api_key_env':'UNUSED','api_key':'MUST_NOT_EXPORT'}}
        with patch('vision_rsi.harness.revision',return_value='fixture'):
            self.interface=build(self.session,self.root/'artifacts')
        self.artifact=build_executable(self.session,self.interface,self.config,self.storage,self.root/'artifacts')
        self.folder=Path(self.artifact['directory'])

    def run_harness(self,*args):
        return subprocess.run([sys.executable,str(self.folder/'harness.py'),*args],capture_output=True,text=True,encoding='utf-8',cwd=self.root,timeout=20)

    def test_standalone_controls_keep_original_session_and_never_export_key(self):
        result=self.run_harness('check');self.assertEqual(result.returncode,0,result.stderr)
        checked=json.loads(result.stdout);self.assertFalse(checked['model_quality_verified'])
        self.assertEqual(checked['video_decoders']['clip']['status'],'ready')
        self.assertEqual(checked['video_decoders']['clip']['plan']['fps'],2)
        self.assertNotIn('MUST_NOT_EXPORT',(self.folder/'config.json').read_text())
        prepared=self.run_harness('training','--action','prepare');self.assertEqual(prepared.returncode,0,prepared.stderr)
        plan=json.loads(prepared.stdout);self.assertEqual(plan['status'],'blocked')
        self.assertEqual(plan['session_id'],self.session['session_id']);self.assertEqual(plan['git_revision'],'fixture')
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual(self.store.show(self.session['session_id'])['versions'][-1]['contract']['budget'],self.session['versions'][-1]['contract']['budget'])
        self.assertEqual(build_executable(self.session,self.interface,self.config,self.storage,self.root/'artifacts')['bundle_id'],self.artifact['bundle_id'])

    def test_changed_original_requirements_block_training(self):
        contract=self.session['versions'][-1]['contract'];contract['goal']='Changed task'
        self.store.define(self.session['session_id'],contract)
        result=self.run_harness('training','--action','prepare')
        self.assertNotEqual(result.returncode,0);self.assertIn('rebuild',result.stderr)

    def test_test_requires_validated_version_and_never_runs_placeholder_predictions(self):
        result=self.run_harness('test','--input','missing.jpg')
        self.assertNotEqual(result.returncode,0);self.assertIn('explicit validated',result.stderr)
        result=self.run_harness('test','--input','missing.jpg','--version','unvalidated')
        self.assertNotEqual(result.returncode,0);self.assertIn('No validated capability',result.stderr)

    def test_source_change_and_unverified_bytecode_are_rejected(self):
        path=self.folder/'vision_rsi/runner.py';original=path.read_bytes();path.write_text('raise RuntimeError("must not execute")')
        result=self.run_harness('check');self.assertNotEqual(result.returncode,0);self.assertIn('artifact changed',result.stderr)
        path.write_bytes(original)
        extra=self.folder/'vision_rsi/__pycache__';extra.mkdir();(extra/'runner.fake.pyc').write_bytes(b'unverified')
        result=self.run_harness('check');self.assertNotEqual(result.returncode,0);self.assertIn('Unexpected runtime',result.stderr)
        shutil.rmtree(extra)
