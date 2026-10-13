import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.intent import resolve
from vision_rsi.contracts import Sessions
from vision_rsi.training_cli import main


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Sessions(self.root/'sessions')
        self.sid=self.store.create('intent','猫狗识别')['session_id']
        self.contract=json.loads(Path('examples/interface-contract.json').read_text())
        self.session=self.store.define(self.sid,self.contract)
        self.config=self.root/'config.json';self.config.write_text('{"llm":{}}')

    @patch('vision_rsi.intent.OpenAICompatibleClient')
    def test_model_receives_state_displayed_question_and_dialogue_and_receipt_is_saved(self,client):
        client.return_value.complete.return_value={'content':json.dumps({'action':'clarify','reason':'回答任务问题','reply':''})}
        result=resolve('是的',self.session,{},self.root/'harness','每张图只有一只动物吗？',[{'user':'先别执行'}])
        self.assertEqual(result['action'],'clarify')
        messages=client.return_value.complete.call_args.args[0]
        context=json.loads(messages[1]['content'])
        self.assertEqual(context['shown_to_user'],'每张图只有一只动物吗？')
        self.assertEqual(context['active_contract'],self.contract)
        self.assertEqual(context['recent_interaction'],[{'user':'先别执行'}])
        record=json.loads(next((self.root/'harness').rglob('*.json')).read_text())
        self.assertEqual(record['state'],'validated')
        self.assertEqual(record['decision'],result)

    @patch('vision_rsi.intent.OpenAICompatibleClient')
    def test_invalid_actions_and_approval_without_pending_draft_are_not_applied(self,client):
        for action in ('shell','/run','accept','reject'):
            client.return_value.complete.return_value={'content':json.dumps({'action':action,'reason':'test','reply':''})}
            with self.assertRaises(ValueError):resolve('随便运行',self.session,{},self.root/'harness','',[])
        self.assertEqual(client.return_value.complete.call_count,4)
        self.assertTrue(all(json.loads(p.read_text())['state']=='not_applied' for p in (self.root/'harness').rglob('*.json')))

    @patch('vision_rsi.intent.OpenAICompatibleClient')
    def test_failure_is_recorded_without_automatic_retry(self,client):
        client.return_value.complete.side_effect=RuntimeError('unknown API outcome')
        with self.assertRaises(RuntimeError):resolve('往下做',self.session,{},self.root/'harness','',[])
        self.assertEqual(client.return_value.complete.call_count,1)
        self.assertEqual(json.loads(next((self.root/'harness').rglob('*.json')).read_text())['state'],'not_applied')

    def test_explanation_stop_and_mixed_requirement_changes_never_dispatch_execution(self):
        turns=['为什么一直启动不了','别往下跑了','先换数据再跑']
        decisions=[{'action':'explain','reason':'询问失败原因','reply':'缺少训练后端。'},
                   {'action':'stop','reason':'停止推进','reply':''},
                   {'action':'clarify','reason':'先修改需求','reply':''}]
        with patch('builtins.input',side_effect=turns+['/quit']), \
                patch('vision_rsi.intent.resolve',side_effect=decisions) as router, \
                patch('vision_rsi.training_cli.interactive_action',return_value=False) as dispatch, \
                patch.object(Sessions,'clarify',return_value=self.session) as clarify, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            main(['show','--session-id',self.sid,'--sessions',str(self.root/'sessions'),
                  '--config',str(self.config),'--harness-root',str(self.root/'harness'),'--interactive'])
        self.assertEqual(router.call_count,3)
        self.assertEqual(dispatch.call_count,1)
        self.assertEqual(dispatch.call_args.args[0],turns[-1])
        self.assertEqual(clarify.call_args.args[-1],turns[-1])
        self.assertIn('缺少训练后端',output.getvalue())

    def test_unlisted_wording_uses_model_intent_to_advance(self):
        with patch('builtins.input',side_effect=['照刚才那条路线往下做就好','/quit']), \
                patch('vision_rsi.intent.resolve',return_value={'action':'advance','reason':'继续已定方案','reply':''}), \
                patch('vision_rsi.training_cli.interactive_action',return_value=True) as dispatch, \
                contextlib.redirect_stdout(io.StringIO()):
            main(['show','--session-id',self.sid,'--sessions',str(self.root/'sessions'),
                  '--config',str(self.config),'--interactive'])
        self.assertEqual(dispatch.call_args.args[0],'/harness-next')

    def test_router_failure_leaves_session_and_execution_untouched(self):
        before=self.store.show(self.sid)
        with patch('builtins.input',side_effect=['执行一下','/quit']), \
                patch('vision_rsi.intent.resolve',side_effect=ValueError('malformed result')), \
                patch('vision_rsi.training_cli.interactive_action') as dispatch, \
                patch.object(Sessions,'clarify') as clarify,contextlib.redirect_stdout(io.StringIO()):
            main(['show','--session-id',self.sid,'--sessions',str(self.root/'sessions'),
                  '--config',str(self.config),'--interactive'])
        dispatch.assert_not_called();clarify.assert_not_called()
        self.assertEqual(self.store.show(self.sid),before)


if __name__=='__main__':unittest.main()
