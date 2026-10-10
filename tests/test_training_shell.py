import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.training_cli import interactive_action, main


class TrainingShellTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(sessions='sessions',config='local.json',run_store='runs',
            campaign_store='campaigns',registry='registry',steps=3,watch_seconds=120,
            poll_seconds=15,research_rounds=2,campaign_id='saved-campaign',candidate_id=None,
            candidate_module=None,candidate_store='candidates',run_id='saved-run',output=None)

    def test_execution_reuses_scope_and_frozen_campaign_settings(self):
        args=self.settings()
        with patch('vision_rsi.training_cli.main') as invoke:
            for command,action in (('/prepare','prepare'),('/run','advance'),('/watch','watch'),
                    ('/status','agent-status'),('/job','status'),('/logs','logs'),
                    ('/pause','agent-pause'),('/resume','agent-resume')):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(interactive_action(command,'original-session',args))
                actual=invoke.call_args.args[0]
                self.assertEqual(actual[0],action)
                for flag,value in (('--session-id','original-session'),('--sessions','sessions'),
                        ('--run-store','runs'),('--campaign-store','campaigns'),('--registry','registry')):
                    self.assertEqual(actual[actual.index(flag)+1],value)
                self.assertNotIn('--interactive',actual)
                if action in ('advance','watch','agent-status','agent-pause','agent-resume'):
                    self.assertEqual(actual[actual.index('--research-rounds')+1],'2')
                    self.assertEqual(actual[actual.index('--campaign-id')+1],'saved-campaign')
                    self.assertEqual(actual[actual.index('--watch-seconds')+1],'120')
                if action in ('status','logs'):
                    self.assertEqual(actual[actual.index('--run-id')+1],'saved-run')

    def test_unknown_commands_and_interrupted_execution_do_not_become_llm_prompts(self):
        with patch('vision_rsi.training_cli.main',side_effect=SystemExit(1)) as invoke, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(interactive_action('/unknown','session',self.settings()))
            self.assertTrue(interactive_action('/run extra','session',self.settings()))
            self.assertFalse(interactive_action('/show','session',self.settings()))
            self.assertFalse(interactive_action('补充目标','session',self.settings()))
            invoke.assert_not_called()
            self.assertTrue(interactive_action('/run','session',self.settings()))
            invoke.assert_called_once()

    def test_budget_shortcut_forwards_only_explicit_number_without_llm(self):
        with patch('vision_rsi.training_cli.main') as invoke,contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(interactive_action('/budget','session',self.settings()))
            invoke.assert_not_called()
            self.assertTrue(interactive_action('/budget 32','session',self.settings()))
            actual=invoke.call_args.args[0]
            self.assertEqual(actual[0],'budget')
            self.assertEqual(actual[actual.index('--gpu-hours')+1],'32')

    def test_interactive_prepare_keeps_original_contract_and_blocks_missing_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sessions=root/'sessions';store=Sessions(sessions)
            session=store.create('inspection','Joint inspection')
            contract=json.loads(Path('examples/interface-contract.json').read_text(encoding='utf-8'))
            session=store.define(session['session_id'],contract)
            config=root/'config.json';config.write_text(json.dumps({'remote':{},'llm':{}}))
            output=io.StringIO()
            with patch('builtins.input',side_effect=['/prepare','/show','/unknown','/quit']), \
                    patch.object(Sessions,'clarify') as clarify,contextlib.redirect_stdout(output):
                main(['show','--session-id',session['session_id'],'--sessions',str(sessions),
                      '--config',str(config),'--output',str(root/'plans'),'--interactive'])
            clarify.assert_not_called()
            self.assertIn('执行条件待补充',output.getvalue())
            self.assertIn('未知命令',output.getvalue())
            self.assertEqual(store.show(session['session_id'])['versions'],session['versions'])
            self.assertEqual(len(store.list()),1)
            plans=list((root/'plans').rglob('plan.json'))
            self.assertEqual(len(plans),1)
            self.assertEqual(json.loads(plans[0].read_text(encoding='utf-8'))['status'],'blocked')

    def test_explicit_run_cannot_cross_the_interactive_task_session(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch('vision_rsi.training_runs.TrainingRuns') as runs, \
                patch('vision_rsi.training_runs.observe') as observe, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            runs.return_value.get.return_value={'session_id':'other-session'}
            with self.assertRaises(SystemExit):
                main(['status','--session-id','original-session','--run-id','other-run',
                      '--sessions',str(Path(tmp)/'sessions'),'--config',str(Path(tmp)/'missing-config.json')])
            self.assertIn('another task session',errors.getvalue())
            observe.assert_not_called()
            runs.return_value.close.assert_called_once()
