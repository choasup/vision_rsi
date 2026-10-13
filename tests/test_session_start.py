import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.training_cli import main


class SessionStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Sessions(self.root/'sessions')
        self.args=['start','--task-id','catdog','--sessions',str(self.store.root)]

    def create(self,goal='猫狗分类'):
        return self.store.create('catdog',goal)['session_id']

    def test_single_existing_session_resumes_without_prompt_api_or_new_definition(self):
        sid=self.create()
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        self.store.define(sid,contract)
        before=self.store.show(sid)
        with patch('builtins.input',side_effect=['/quit']) as read, patch.object(Sessions,'clarify') as clarify, contextlib.redirect_stdout(io.StringIO()) as output:
            main(self.args+['--goal','different','--contract','missing.json','--interactive'])
        self.assertEqual(read.call_count,1)
        clarify.assert_not_called()
        self.assertIn('已恢复会话',output.getvalue())
        self.assertEqual(self.store.show(sid),before)
        self.assertEqual(len(self.store.list()),1)

    def test_multiple_sessions_show_summary_and_select_existing(self):
        older=self.create('整图分类');newer=self.create('框出动物位置')
        with patch('builtins.input',side_effect=['invalid','2','/quit']), patch.object(Sessions,'clarify') as clarify, contextlib.redirect_stdout(io.StringIO()) as output:
            main(self.args+['--interactive'])
        clarify.assert_not_called()
        self.assertIn('整图分类',output.getvalue())
        self.assertIn('框出动物位置',output.getvalue())
        self.assertIn('最近输入',output.getvalue())
        self.assertIn('已恢复会话。session_id: '+older,output.getvalue())
        self.assertEqual(len(self.store.list()),2)

    def test_multiple_sessions_can_select_full_id_or_cancel_without_creation(self):
        sid=self.create();self.create()
        for inputs in ([sid,'/quit'],['/quit']):
            with patch('builtins.input',side_effect=inputs), contextlib.redirect_stdout(io.StringIO()):
                main(self.args+['--interactive'])
            self.assertEqual(len(self.store.list()),2)

    def test_noninteractive_ambiguity_returns_json_and_does_not_guess(self):
        self.create();self.create()
        with patch('builtins.input') as read, contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as error:main(self.args+['--json'])
        self.assertEqual(error.exception.code,2)
        read.assert_not_called()
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'selection_required')
        self.assertEqual(len(result['sessions']),2)
        self.assertEqual(len(self.store.list()),2)

    def test_explicit_new_preserves_old_and_selected_session_validates_task(self):
        sid=self.create();before=self.store.show(sid)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main(self.args+['--new-session','--goal','新的实验','--offline','--json'])
        created=json.loads(output.getvalue())
        self.assertNotEqual(created['session_id'],sid)
        self.assertEqual(self.store.show(sid),before)
        other=self.store.create('other','其他任务')['session_id']
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            main(self.args+['--session-id',other])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main(self.args+['--session-id',sid,'--json'])
        self.assertEqual(json.loads(output.getvalue())['session_id'],sid)

    def test_resume_preserves_pending_request_without_automatic_retry(self):
        sid=self.create()
        with self.store.db() as db:db.execute('UPDATE sessions SET pending=1 WHERE id=?',(sid,))
        with patch.object(Sessions,'clarify') as clarify, contextlib.redirect_stdout(io.StringIO()) as output:
            main(self.args+['--json'])
        clarify.assert_not_called()
        self.assertTrue(json.loads(output.getvalue())['pending_request'])
        self.assertEqual(len(self.store.list()),1)

    def test_concurrent_default_starts_create_one_session(self):
        # Initialize schema before exercising concurrent opening transactions.
        self.store.list()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:Sessions(self.store.root).start('catdog','猫狗分类'),range(2)))
        self.assertEqual({result['status'] for result in results},{'created','resumed'})
        self.assertEqual(len({result['session']['session_id'] for result in results}),1)
        self.assertEqual(len(self.store.list()),1)

    def test_cancel_new_goal_does_not_leave_empty_session(self):
        with patch('builtins.input',side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            main(self.args+['--interactive'])
        self.assertEqual(self.store.list(),[])


if __name__=='__main__':unittest.main()
