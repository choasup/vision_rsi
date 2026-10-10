import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.workspace import initialize


class WorkspaceInitTests(unittest.TestCase):
    @patch.dict(os.environ,{'DEEPSEEK_API_KEY':'fixture-secret-never-copy'})
    def test_creates_template_without_secret_or_budget_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'new workspace'
            result=initialize(root)
            path=root/'config.local.json'
            before=path.read_bytes()
            config=json.loads(before)
            self.assertEqual(config['budget_gpu_hours'],0)
            self.assertEqual(config['max_experiments'],0)
            self.assertEqual(config['llm']['api_key_env'],'DEEPSEEK_API_KEY')
            self.assertNotIn('fixture-secret',before.decode())
            self.assertFalse(result['gpu_training_authorized'])
            self.assertFalse(result['configuration_ready'])
            self.assertEqual(list(root.iterdir()),[path])
            with self.assertRaises(FileExistsError):initialize(root)
            self.assertEqual(path.read_bytes(),before)

    def test_actual_source_launcher_defaults_to_caller_workspace(self):
        launcher=Path(__file__).resolve().parents[1]/'launch_agent.py'
        with tempfile.TemporaryDirectory() as folder:
            command=[sys.executable,'-X','utf8',str(launcher),'--cli','workspace-init']
            result=subprocess.run(command,cwd=folder,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['directory'],str(Path(folder).resolve()))
            self.assertTrue((Path(folder)/'config.local.json').is_file())
            result=subprocess.run(command,cwd=folder,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertNotEqual(result.returncode,0)
