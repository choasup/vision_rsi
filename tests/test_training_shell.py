import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions, GPU_BUDGET_QUESTION
from vision_rsi.training_cli import interactive_action, main, execution_summary, conversation_summary, review_action


class TrainingShellTests(unittest.TestCase):
    def test_natural_progress_checks_real_prerequisites_without_llm_or_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Sessions(root/'sessions')
            created=store.create('catdog','猫狗分类')
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            contract['budget']={'gpu_hours':10}
            store.define(created['session_id'],contract)
            before=(store.root/'sessions.sqlite3').read_bytes()
            config=root/'config.json';config.write_text('{"llm":{},"remote":{}}')
            output=io.StringIO()
            with patch('builtins.input',side_effect=['推进','/quit']), \
                    patch.object(Sessions,'clarify') as clarify,contextlib.redirect_stdout(output):
                main(['show','--session-id',created['session_id'],'--sessions',str(store.root),
                      '--run-store',str(root/'runs'),'--config',str(config),'--interactive'])
            clarify.assert_not_called()
            self.assertIn('只读本地就绪检查: blocked',output.getvalue())
            self.assertIn('缺少此任务的训练后端',output.getvalue())
            self.assertIn('这是代码开发工作',output.getvalue())
            self.assertEqual(before,(store.root/'sessions.sqlite3').read_bytes())
            self.assertFalse((root/'runs').exists())

    def test_unsupported_complete_task_does_not_display_model_execution_claim(self):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        result={'versions':[{'contract':contract,'issues':[],
                'assistant_message':'可以按此推进执行，已经准备好了。'}],
                'turns':[{'role':'user','content':'是'}]}
        text=conversation_summary(result)
        self.assertNotIn('可以按此推进执行',text)
        self.assertIn('缺少对应的训练后端',text)

    def test_budget_is_deferred_without_losing_execution_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Sessions(tmp);result=store.create('catdog','猫狗识别')
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            contract['budget']=None;contract['open_questions']=[GPU_BUDGET_QUESTION]
            result=store.define(result['session_id'],contract)
            text=conversation_summary(result)
            self.assertNotIn('接下来请回答：'+GPU_BUDGET_QUESTION,text)
            self.assertIn('GPU 预算可等准备训练时再设置',text)
            self.assertIn('自动训练尚未支持此任务',text)
            self.assertIn('缺少资源预算',store.show(result['session_id'])['versions'][-1]['issues'])
            self.assertIsNone(store.show(result['session_id'])['versions'][-1]['contract']['budget'])

    def test_task_question_precedes_gpu_budget_and_advice_has_legacy_fallback(self):
        result={'versions':[{'contract':{'goal':'猫狗识别','open_questions':[
                    GPU_BUDGET_QUESTION,'判断整张图的类别，还是标出每只动物的位置？']},'issues':['missing']}],
                'turns':[{'role':'user','content':'给我建议'}]}
        text=conversation_summary(result)
        self.assertIn('建议先完成需求定义',text)
        self.assertIn('接下来请回答：判断整张图',text)
        self.assertNotIn('接下来请回答：'+GPU_BUDGET_QUESTION,text)
        self.assertEqual(len(result['versions'][0]['contract']['open_questions']),2)

    def test_advice_is_displayed_persisted_and_does_not_authorize_a_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Sessions(root/'sessions')
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            contract['budget']=None;contract['open_questions']=[GPU_BUDGET_QUESTION]
            created=store.create('catdog','猫狗识别')
            store.define(created['session_id'],contract)
            response=dict(contract,assistant_message='建议先只整理需求；训练设备确定后再估算用量，现在无需填写预算。')
            config=root/'config.json';config.write_text('{"llm":{}}')
            output=io.StringIO()
            with patch('vision_rsi.contracts.OpenAICompatibleClient') as client, \
                    patch('builtins.input',side_effect=['给我建议','给我建议','/quit']), \
                    contextlib.redirect_stdout(output):
                client.return_value.complete.return_value={'content':json.dumps(response)}
                main(['show','--session-id',created['session_id'],'--sessions',str(store.root),
                      '--config',str(config),'--interactive'])
            saved=Sessions(store.root).show(created['session_id'])
            self.assertEqual(saved['versions'][-1]['contract'],contract)
            self.assertEqual(saved['versions'][-1]['assistant_message'],response['assistant_message'])
            self.assertNotIn('review_required',saved['versions'][-1])
            self.assertNotIn('assistant_message',saved['versions'][-1]['contract'])
            self.assertIn(response['assistant_message'],output.getvalue())
            self.assertNotIn('接下来请回答：'+GPU_BUDGET_QUESTION,output.getvalue())

    def test_review_shows_new_goal_and_natural_confirmation_persists_exact_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Sessions(root/'sessions')
            result=store.create('catdog','做猫狗识别分类')
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            contract['goal']='识别图片中的猫和狗'
            store.define(result['session_id'],contract)
            proposed=json.loads(json.dumps(contract))
            proposed['goal']='区分图片中的猫、狗和其他动物'
            proposed['acceptance']['threshold']=0.6
            proposed['budget']['gpu_hours']=20
            with patch('vision_rsi.contracts.OpenAICompatibleClient') as client:
                client.return_value.complete.return_value={'content':json.dumps(proposed)}
                pending=store.clarify(result['session_id'],{},'增加其他动物类别')
            text=conversation_summary(pending)
            self.assertIn(proposed['goal'],text)
            self.assertNotIn('我理解你想做：'+contract['goal']+'\n',text)
            self.assertIn('0.8 → 0.6',text)
            self.assertIn('资源预算',text)
            self.assertIn('输入“是”确认',text)
            self.assertNotIn('Harness',text)
            config=root/'config.json';config.write_text('{}')
            with patch('builtins.input',side_effect=['是','/quit']), \
                    patch.object(Sessions,'clarify') as clarify,contextlib.redirect_stdout(io.StringIO()):
                main(['show','--session-id',result['session_id'],'--sessions',str(root/'sessions'),
                      '--config',str(config),'--interactive'])
            clarify.assert_not_called()
            accepted=store.show(result['session_id'])
            self.assertEqual(accepted['versions'][-1]['contract'],proposed)
            self.assertIsNone(review_action('是',accepted))

    def test_plain_no_rejects_draft_without_llm_or_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Sessions(root/'sessions')
            result=store.create('inspection','检查缺陷')
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            store.define(result['session_id'],contract)
            proposed=json.loads(json.dumps(contract));proposed['budget']['gpu_hours']=100
            with patch('vision_rsi.contracts.OpenAICompatibleClient') as client:
                client.return_value.complete.return_value={'content':json.dumps(proposed)}
                store.clarify(result['session_id'],{},'继续')
            with patch('builtins.input',side_effect=['否','/quit']), \
                    patch.object(Sessions,'clarify') as clarify,contextlib.redirect_stdout(io.StringIO()):
                main(['show','--session-id',result['session_id'],'--sessions',str(root/'sessions'),'--interactive'])
            clarify.assert_not_called()
            self.assertEqual(store.show(result['session_id'])['versions'][-1]['contract'],contract)

    def test_placeholder_goal_is_replaced_before_first_model_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Sessions(Path(tmp)/'sessions')
            config=Path(tmp)/'config.json';config.write_text('{"llm":{}}')
            def clarify(session,config,message=None):return store.show(session)
            with patch('builtins.input',side_effect=['做猫狗识别分类','/quit']) as read, \
                    patch.object(Sessions,'clarify',side_effect=clarify),contextlib.redirect_stdout(io.StringIO()):
                main(['start','--task-id','catdog','--goal','Describe requirements',
                      '--sessions',str(store.root),'--config',str(config),'--interactive'])
            saved=store.show(store.list()[0]['session_id'])
            self.assertEqual(saved['turns'][0]['content'],'做猫狗识别分类')
            self.assertIn('你想完成什么任务',read.call_args_list[0].args[0])

    def test_conversation_asks_one_question_and_keeps_all_missing_facts(self):
        result={'versions':[{'contract':{'goal':'猫狗分类',
                'open_questions':['你有训练数据吗？','准确率要达到多少？']},'issues':['missing']} ]}
        text=conversation_summary(result)
        self.assertIn('你有训练数据吗？',text)
        self.assertNotIn('准确率要达到多少？',text)
        self.assertEqual(len(result['versions'][0]['contract']['open_questions']),2)
        self.assertNotIn('/run',text)

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
