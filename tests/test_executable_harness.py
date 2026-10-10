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
    def test_transient_windows_publication_lock_retries_same_staging_directory(self):
        original=Path.rename
        attempts=[]
        (self.root/'locked-export').mkdir()
        def locked_once(path,target):
            attempts.append((path,target))
            if len(attempts)==1:raise PermissionError('temporary file scanner lock')
            return original(path,target)
        with patch.object(Path,'rename',locked_once),patch('vision_rsi.executable_harness.time.sleep') as sleep:
            artifact=build_executable(self.session,self.interface,self.config,self.storage,self.root/'locked-export')
        self.assertEqual(len(attempts),2)
        self.assertEqual(attempts[0],attempts[1])
        sleep.assert_called_once_with(.1)
        self.assertTrue((Path(artifact['directory'])/'manifest.json').is_file())

    def test_frozen_event_evaluator_uses_task_threshold_and_preserves_bundle(self):
        from vision_rsi.contracts import EVENT_PROTOCOL
        contract=json.loads(json.dumps(self.session['versions'][-1]['contract']))
        contract['acceptance']={'metric':'event_micro_f1','direction':'maximize','threshold':.9,
                                'iou_threshold':.75,'evaluation_protocol':EVENT_PROTOCOL}
        contract['output_schema']={'type':'object','properties':{'events':{'type':'array','items':{'type':'object','properties':{}}}}}
        contract['example_output']={'events':[]}
        separate=self.store.create('event-fixture','Synthetic event evaluator')['session_id']
        session=self.store.define(separate,contract)
        interface=build(session,self.root/'event-artifacts')
        artifact=build_executable(session,interface,self.config,self.storage,self.root/'event-artifacts')
        self.folder=Path(artifact['directory'])
        checked=json.loads(self.run_harness('check').stdout)
        self.assertEqual(checked['evaluation_modes'],['evaluate-events'])
        self.assertFalse(checked['training_adapter']['implementation_supported'])
        original={str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        gt={'labels':['action'],'samples':[{'sample_id':'clip','events':[{'label':'action','start_seconds':0,'end_seconds':2}]}]}
        pred=json.loads(json.dumps(gt));pred['samples'][0]['events'][0]['end_seconds']=1
        ground=self.root/'gt.json';prediction=self.root/'prediction.json';output=self.root/'evaluation.json'
        ground.write_text(json.dumps(gt));prediction.write_text(json.dumps(pred))
        args=['evaluate-events','--ground-truth',str(ground),'--predictions',str(prediction),'--output',str(output)]
        result=self.run_harness(*args)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(output.read_text())
        self.assertEqual(report['tp'],0);self.assertEqual(report['iou_threshold'],.75)
        self.assertTrue(report['contract_bound']);self.assertFalse(report['metric_threshold_met'])
        self.assertEqual(report['harness_bundle_id'],artifact['bundle_id'])
        before=output.read_bytes()
        self.assertNotEqual(self.run_harness(*args).returncode,0)
        self.assertEqual(before,output.read_bytes())
        args[-1]=str(self.folder/'new-evaluation.json')
        self.assertNotEqual(self.run_harness(*args).returncode,0)
        self.assertEqual(original,{str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()})

    def test_frozen_evaluator_rejects_incompatible_task(self):
        result=self.run_harness('evaluate-events','--ground-truth','unused.json','--predictions','unused.json',
                                '--output',str(self.root/'evaluation.json'))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Contract must specify',result.stderr)
        self.assertFalse((self.root/'evaluation.json').exists())

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
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
        self.session=self.store.define(session['session_id'],contract)
        self.config={'remote':{'ssh_host':'fixture','workspace':'/workspace','coco_root':''},
                     'llm':{'model':'fixture','base_url':'https://fixture.invalid','api_key_env':'UNUSED','api_key':'MUST_NOT_EXPORT',
                            'usage_ledger':str(self.root/'shared-usage.sqlite3'),'usage_call_limit':10}}
        with patch('vision_rsi.harness.revision',return_value='fixture'):
            self.interface=build(self.session,self.root/'artifacts')
        self.artifact=build_executable(self.session,self.interface,self.config,self.storage,self.root/'artifacts')
        self.folder=Path(self.artifact['directory'])

    def run_harness(self,*args):
        # Match run.cmd's UTF-8 process mode rather than depending on the
        # developer shell's PYTHONUTF8 setting on Chinese Windows systems.
        return subprocess.run([sys.executable,'-X','utf8',str(self.folder/'harness.py'),*args],capture_output=True,text=True,encoding='utf-8',cwd=self.root,timeout=20)

    def test_standalone_controls_keep_original_session_and_never_export_key(self):
        result=self.run_harness('check');self.assertEqual(result.returncode,0,result.stderr)
        checked=json.loads(result.stdout);self.assertFalse(checked['model_quality_verified'])
        self.assertFalse(checked['training_adapter']['implementation_supported'])
        self.assertIsNone(checked['training_adapter']['adapter_id'])
        self.assertEqual(checked['video_decoders']['clip']['status'],'ready')
        self.assertEqual(checked['video_decoders']['clip']['plan']['fps'],2)
        self.assertNotIn('MUST_NOT_EXPORT',(self.folder/'config.json').read_text())
        self.assertEqual(json.loads((self.folder/'config.json').read_text())['llm']['usage_ledger'],
                         self.config['llm']['usage_ledger'])
        self.assertEqual(json.loads((self.folder/'config.json').read_text())['llm']['usage_call_limit'],10)
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

    def test_export_keeps_optional_controller_attempt_cap(self):
        config=dict(self.config,controller={'tool_attempt_limit':5})
        artifact=build_executable(self.session,self.interface,config,self.storage,self.root/'artifacts')
        exported=json.loads((Path(artifact['directory'])/'config.json').read_text())
        self.assertEqual(exported['controller'],{'tool_attempt_limit':5})
        with self.assertRaises(ValueError):
            build_executable(self.session,self.interface,dict(config,controller={'tool_attempt_limit':True}),self.storage,self.root/'artifacts')
