import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.training_cli import interactive_action, main, execution_summary


class TrainingShellTests(unittest.TestCase):
    def test_json_watch_progress_uses_module_stderr_without_local_import_shadowing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.json'
            config.write_text(json.dumps({'remote':{},'llm':{}}))
            def watcher(*args):
                args[-1]({'status':'waiting','run_id':'existing-run'})
                return {'status':'waiting','watch':{'stop_reason':'duration_elapsed'}}
            output=io.StringIO();errors=io.StringIO()
            with patch('vision_rsi.watch.watch',side_effect=watcher), \
                    contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):
                main(['watch','--session-id','existing-session','--sessions',str(root/'sessions'),
                      '--config',str(config),'--json'])
            self.assertEqual(json.loads(errors.getvalue())['run_id'],'existing-run')
            self.assertEqual(json.loads(output.getvalue())['status'],'waiting')

    def test_campaign_summary_exposes_nested_blockers_and_exact_identity(self):
        result={'status':'blocked','campaign_id':'campaign-a','session_id':'session-a','paused':False,
                'state_path':'state.json','plan':{'plan_path':'plan.json','blockers':['需要真实GPU预算']}}
        text=execution_summary(result)
        for expected in ('Campaign: campaign-a','会话: session-a','控制记录: state.json',
                         '计划文件: plan.json','需要真实GPU预算','继续决策: 未暂停'):
            self.assertIn(expected,text)

    def test_exhausted_summary_preserves_uncertain_intent_and_does_not_suggest_reset(self):
        result={'status':'controller_budget_exhausted','paused':True,'run_id':'original-run',
                'controller_tool_budget':{'limit':1,'admitted_attempts':1,'remaining_attempts':0},
                'intent':{'action':{'kind':'observe'},'status':'reserved','tool_attempts':[{'status':'started'}]}}
        text=execution_summary(result)
        for expected in ('1 / 1；剩余 0','待处理动作: observe','已预留尝试 1',
                         '恢复不会刷新上限','training status/logs','远端作业不会因此取消'):
            self.assertIn(expected,text)
        self.assertNotIn('可 agent-resume',text)

    def settings(self):
        return SimpleNamespace(sessions='sessions',config='local.json',run_store='runs',
            campaign_store='campaigns',registry='registry',steps=3,watch_seconds=120,
            poll_seconds=15,research_rounds=2,campaign_id='saved-campaign',candidate_id=None,
            candidate_module=None,candidate_store='candidates',run_id='saved-run',output=None,
            research_root='task-research',repository='source-repo',research_watch_turns=4)

    def test_general_research_shell_preserves_repository_and_limits(self):
        args=self.settings()
        with patch('vision_rsi.training_cli.main') as invoke:
            for command in ('/research','/research-watch','/research-status','/research-pause','/research-resume','/select','/release'):
                self.assertTrue(interactive_action(command,'original-session',args))
                actual=invoke.call_args.args[0]
                self.assertEqual(actual[actual.index('--session-id')+1],'original-session')
                if command!='/release':
                    self.assertEqual(actual[actual.index('--research-root')+1],'task-research')
                if command in ('/research','/research-watch'):
                    self.assertEqual(actual[actual.index('--repository')+1],'source-repo')
                    self.assertEqual(actual[actual.index('--research-watch-turns')+1],'4')
                    self.assertEqual(actual[actual.index('--watch-seconds')+1],'120')

    def test_delivery_shell_preserves_windows_path_and_explicit_acceptance_target(self):
        with patch('vision_rsi.training_cli.main') as invoke:
            self.assertTrue(interactive_action('/deliver "F:\\holdout data\\acceptance.json" 30','session',self.settings()))
            actual=invoke.call_args.args[0]
            self.assertEqual(actual[0],'deliver-candidate')
            self.assertIn('--select-development',actual)
            self.assertEqual(actual[actual.index('--dataset')+1],r'F:\holdout data\acceptance.json')
            self.assertEqual(actual[actual.index('--max-latency-seconds')+1],'30')
            self.assertEqual(actual[actual.index('--research-root')+1],'task-research')
            self.assertTrue(interactive_action('/delivery source-version','session',self.settings()))
            actual=invoke.call_args.args[0]
            self.assertEqual(actual[0],'delivery-status')
            self.assertEqual(actual[actual.index('--version')+1],'source-version')

    def test_incomplete_delivery_commands_never_execute_or_become_prompts(self):
        with patch('vision_rsi.training_cli.main') as invoke,contextlib.redirect_stdout(io.StringIO()):
            for command in ('/deliver','/deliver file.json','/deliver "unclosed','/delivery','/delivery one two','/select extra'):
                self.assertTrue(interactive_action(command,'session',self.settings()))
            invoke.assert_not_called()

    def test_execution_reuses_scope_and_frozen_campaign_settings(self):
        args=self.settings()
        with patch('vision_rsi.training_cli.main') as invoke:
            for command,action in (('/readiness','readiness'),('/prepare','prepare'),('/run','advance'),('/watch','watch'),
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
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
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
