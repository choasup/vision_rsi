import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('launcher',Path(__file__).resolve().parents[1]/'launch_agent.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class LauncherPathsTests(unittest.TestCase):
    def test_real_launcher_from_external_directory_reads_caller_session_store(self):
        from vision_rsi.contracts import Sessions
        with tempfile.TemporaryDirectory() as directory:
            session=Sessions(Path(directory)/'sessions').create('caller-task','Synthetic launcher fixture')
            process=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),
                                    '--cli','training','list','--sessions','sessions','--json'],cwd=directory,
                                   capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(process.returncode,0,process.stderr)
            rows=json.loads(process.stdout)
            self.assertEqual([row['session_id'] for row in rows],[session['session_id']])

    def test_explicit_task_paths_resolve_from_caller_without_rewriting_text_or_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            caller=Path(directory)
            args=['training','start','--goal','检测 ./图片','--config=local.json','--sessions','state sessions','--task-id','abc']
            actual=launcher.task_cli_paths(args,caller)
            self.assertEqual(actual,['training','start','--goal','检测 ./图片','--config='+str((caller/'local.json').resolve()),
                                     '--sessions',str((caller/'state sessions').resolve()),'--task-id','abc'])
            self.assertEqual(launcher.task_cli_paths(['test','--task-id','abc'],caller),['test','--task-id','abc'])
            self.assertEqual(launcher.task_cli_paths(['training','show','--config'],caller),['training','show','--config'])
            self.assertEqual(launcher.task_cli_paths(['test','--input='],caller),['test','--input='])
