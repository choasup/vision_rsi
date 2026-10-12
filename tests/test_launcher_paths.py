import importlib.util
import json
import os
from contextlib import closing
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('launcher',Path(__file__).resolve().parents[1]/'launch_agent.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class LauncherPathsTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows CMD launcher')
    def test_cmd_explicit_python_from_external_directory_and_invalid_override(self):
        from vision_rsi.contracts import Sessions
        wrapper=str(Path(__file__).resolve().parents[1]/'vision-rsi.cmd')
        with tempfile.TemporaryDirectory() as directory:
            session=Sessions(Path(directory)/'sessions').create('external-task','Launcher developer fixture')
            environment=dict(os.environ,VISION_RSI_PYTHON=sys.executable,USERPROFILE=directory)
            command=[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',wrapper,'training','list','--sessions','sessions','--json']
            result=subprocess.run(command,cwd=directory,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)[0]['session_id'],session['session_id'])
            environment['VISION_RSI_PYTHON']=str(Path(directory)/'missing-python.exe')
            result=subprocess.run(command,cwd=directory,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,2)
            self.assertIn('VISION_RSI_PYTHON',result.stderr)

    def call(self,directory,*arguments):
        return subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),
                               '--cli',*arguments],cwd=directory,capture_output=True,text=True,encoding='utf-8',timeout=30)

    def test_event_evaluation_reads_and_writes_caller_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            document={'labels':['event'],'samples':[{'sample_id':'one','events':[
                {'label':'event','start_seconds':0,'end_seconds':1}]}]}
            (root/'events.json').write_text(json.dumps(document))
            result=self.call(directory,'evaluate-events','--ground-truth','events.json',
                             '--predictions=events.json','--output','result.json')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads((root/'result.json').read_text())['event_micro_f1'],1)

    def test_observation_reads_caller_store_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=root/'request store';store.mkdir()
            path=store/'requests.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE requests(id TEXT,context TEXT,state TEXT,response TEXT)')
                db.execute('INSERT INTO requests VALUES (?,?,?,NULL)',('fixture','{}','not_dispatched'));db.commit()
            before=path.read_bytes()
            result=self.call(directory,'experiment-request','--store','request store','--request-id','fixture')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['state'],'not_dispatched')
            self.assertEqual(path.read_bytes(),before)

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

    def test_harness_build_from_external_workspace_keeps_artifacts_in_caller_directory(self):
        from vision_rsi.contracts import Sessions
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Sessions(root/'sessions')
            session=store.create('external-harness','External workspace fixture')
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text())
            store.define(session['session_id'],contract)
            (root/'config.json').write_text('{"research":{},"llm":{},"remote":{}}')
            result=self.call(directory,'training','harness-advance','--session-id',session['session_id'],
                             '--sessions','sessions','--config','config.json','--harness-root','local harness','--json')
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertTrue(Path(report['progress_path']).is_relative_to(root/'local harness'))
            self.assertEqual(report['interface_check']['status'],'interface_checked')
            self.assertEqual(report['status'],'awaiting_generation')

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
