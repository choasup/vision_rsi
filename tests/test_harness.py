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
    def test_standalone_check_reuse_and_tamper(self,_):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        session={'task_id':'inspection','session_id':'fixture','versions':[{'version':1,'contract':contract,'issues':[]}]}
        with tempfile.TemporaryDirectory() as root:
            artifact=build(session,root);folder=Path(artifact['directory'])
            checked=subprocess.run([sys.executable,str(folder/'harness.py'),'check'],capture_output=True,text=True,cwd=root)
            self.assertEqual(checked.returncode,0,checked.stderr)
            self.assertFalse(json.loads(checked.stdout)['model_available'])
            self.assertTrue(build(session,root)['reused'])
            sample=Path(root)/'sample.json';sample.write_text(json.dumps(contract['example_input']))
            result=subprocess.run([sys.executable,str(folder/'harness.py'),'infer','--input',str(sample)],capture_output=True,text=True,cwd=root)
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['status'],'blocked')
            (folder/'interface_runtime.py').write_text('tampered')
            with self.assertRaises(ValueError):build(session,root)
