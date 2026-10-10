import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.harness import build

class HarnessTests(unittest.TestCase):
    @patch('vision_rsi.harness.revision',return_value='fixture')
    def test_runtime_change_builds_new_bundle_and_preserves_original(self,_):
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text())
        session={'task_id':'inspection','session_id':'first','versions':[{'version':1,'contract':contract,'issues':[]}]}
        with tempfile.TemporaryDirectory() as root:
            first=build(session,root);folder=Path(first['directory'])
            original={p.name:p.read_bytes() for p in folder.iterdir()}
            read=Path.read_text
            def changed(path,*args,**kwargs):
                text=read(path,*args,**kwargs)
                return text.replace('GPU_BUDGET_QUESTION =','\n# synthetic runtime revision\nGPU_BUDGET_QUESTION =',1) if path.name=='contracts.py' else text
            with patch.object(Path,'read_text',changed):
                second=build(session,root)
                self.assertTrue(build(session,root)['reused'])
            self.assertNotEqual(first['bundle_id'],second['bundle_id'])
            self.assertNotEqual(first['directory'],second['directory'])
            self.assertEqual(original,{p.name:p.read_bytes() for p in folder.iterdir()})
            other=dict(session,session_id='second')
            self.assertNotEqual(build(other,root)['bundle_id'],first['bundle_id'])
            manifest=json.loads((folder/'manifest.json').read_text())
            manifest['session_id']='wrong'
            (folder/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'metadata conflict'):build(session,root)
            result=subprocess.run([sys.executable,str(folder/'harness.py'),'check'],capture_output=True,text=True,cwd=root)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('differs from identity',result.stderr)

    @patch('vision_rsi.harness.revision',return_value='fixture')
    def test_frozen_event_validation_without_package_imports(self,_):
        from vision_rsi.contracts import EVENT_PROTOCOL
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text())
        contract['acceptance']={'metric':'event_micro_f1','direction':'maximize','threshold':.9,
                                'iou_threshold':.5,'evaluation_protocol':EVENT_PROTOCOL}
        contract['output_schema']={'type':'object','properties':{'events':{'type':'array','items':{'type':'object','properties':{}}}}}
        contract['example_output']={'events':[]}
        session={'task_id':'video-fixture','session_id':'fixture','versions':[{'version':1,'contract':contract,'issues':[]}]}
        with tempfile.TemporaryDirectory() as root:
            folder=Path(build(session,root)['directory'])
            script="""import sys,json
sys.path.insert(0,sys.argv[1])
from interface_runtime import issues
c=json.load(open(sys.argv[1]+'/contract.json',encoding='utf-8'))
assert issues(c)==[]
c['acceptance']['iou_threshold']=None
assert any('iou_threshold' in error for error in issues(c))
assert 'vision_rsi' not in sys.modules
print('standalone event validation passed')
"""
            run=subprocess.run([sys.executable,'-I','-c',script,str(folder)],
                               capture_output=True,text=True,cwd=root)
            self.assertEqual(run.returncode,0,run.stderr)

    @patch('vision_rsi.harness.revision',return_value='fixture')
    def test_standalone_check_reuse_and_tamper(self,_):
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text())
        session={'task_id':'inspection','session_id':'fixture','versions':[{'version':1,'contract':contract,'issues':[]}]}
        with tempfile.TemporaryDirectory() as root:
            artifact=build(session,root);folder=Path(artifact['directory'])
            checked=subprocess.run([sys.executable,str(folder/'harness.py'),'check'],capture_output=True,text=True,cwd=root)
            self.assertEqual(checked.returncode,0,checked.stderr)
            self.assertFalse(json.loads(checked.stdout)['model_available'])
            # Exported validation must work without the source package on sys.path.
            validation=subprocess.run([sys.executable,'-I','-c',
                "import sys,json;sys.path.insert(0,sys.argv[1]);from interface_runtime import issues;print(json.dumps(issues(json.load(open(sys.argv[1]+'/contract.json',encoding='utf-8')))))",
                str(folder)],capture_output=True,text=True,cwd=root)
            self.assertEqual(validation.returncode,0,validation.stderr)
            self.assertEqual(json.loads(validation.stdout),[])
            self.assertTrue(build(session,root)['reused'])
            sample=Path(root)/'sample.json';sample.write_text(json.dumps(contract['example_input']))
            result=subprocess.run([sys.executable,str(folder/'harness.py'),'infer','--input',str(sample)],capture_output=True,text=True,cwd=root)
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['status'],'blocked')
            (folder/'interface_runtime.py').write_text('tampered')
            with self.assertRaises(ValueError):build(session,root)
