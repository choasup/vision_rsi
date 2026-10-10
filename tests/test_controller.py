import tempfile
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from vision_rsi.controller import parse_plan, research_step
from vision_rsi.ledger import Ledger


class ControllerTests(unittest.TestCase):
    @patch('vision_rsi.controller.execute',return_value={'fixture':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_known_not_dispatched_allows_explicit_new_request_without_resetting_limit(self,client,execute):
        from vision_rsi.llm import LLMNotDispatched
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            client.return_value.complete.side_effect=LLMNotDispatched('local fixture refusal')
            config={'llm':{'model':'fixture'},'remote':{}}
            for _ in range(6):
                with self.assertRaises(LLMNotDispatched):research_step(config,folder)
            events=ledger.events()
            requests=[e for e in events if e['payload'].get('record_type')=='planning_request']
            refused=[e for e in events if e['payload'].get('record_type')=='planning_not_dispatched']
            self.assertEqual(len(requests),6);self.assertEqual(len(refused),6)
            self.assertEqual({e['key'] for e in requests},{e['payload']['request_key'] for e in refused})
            research_step(config,folder)
            self.assertEqual(client.return_value.complete.call_count,6)
            execute.assert_not_called()

    @patch('vision_rsi.controller.execute',return_value={'fixture':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_explicit_retry_after_not_dispatched_can_complete(self,client,execute):
        from vision_rsi.llm import LLMNotDispatched
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            config={'llm':{'model':'fixture'},'remote':{}}
            client.return_value.complete.side_effect=LLMNotDispatched('fixture')
            with self.assertRaises(LLMNotDispatched):research_step(config,folder)
            client.return_value.complete.side_effect=None
            client.return_value.complete.return_value={'content':'{"tool":"inspect_repository","summary":"inspect","question":"q","expected_evidence":"e","refs":["goal"]}'}
            research_step(config,folder)
            self.assertEqual(client.return_value.complete.call_count,2)
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['kind'],'result')

    def test_repository_observation_hashes_dirty_source_without_reading_secrets(self):
        import hashlib
        from vision_rsi.controller import execute
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'vision_rsi').mkdir()
            source=root/'vision_rsi/example.py';source.write_bytes(b'print(1)\n')
            (root/'README.md').write_text('fixture')
            (root/'.env').write_text('MUST_NOT_READ')
            def git(*args):
                return subprocess.run(['git',*args],cwd=root,capture_output=True,check=True)
            git('init');git('add','.')
            git('-c','user.name=Fixture','-c','user.email=fixture@local.invalid','commit','-m','fixture')
            first=execute('inspect_repository',{},root)
            self.assertTrue(first['tracked_worktree_clean_before_and_after'])
            self.assertNotIn('.env',first['source_excerpts'])
            self.assertNotIn('MUST_NOT_READ',str(first))
            source.write_bytes(b'print(2)\n')
            second=execute('inspect_repository',{},root)
            self.assertEqual(first['git_revision'],second['git_revision'])
            self.assertFalse(second['tracked_worktree_clean_before_and_after'])
            self.assertEqual(second['source_sha256']['vision_rsi/example.py'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertNotEqual(first['source_sha256'],second['source_sha256'])
            source.write_bytes(b'x'*(1024*1024+1))
            third=execute('inspect_repository',{},root)
            self.assertNotIn('vision_rsi/example.py',third['source_excerpts'])
            self.assertTrue(any(row['reason']=='source_byte_limit' for row in third['skipped_sources']))

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_actual_process_death_releases_lock_and_recovers_pending_action(self,client):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('pending','action',{'executor':'research-v1','tool':'inspect_repository',
                                             'summary':'synthetic crash probe','refs':['goal']})
            program="""import os,sys
import vision_rsi.controller as controller
controller.execute=lambda *args:os._exit(73)
controller.research_step({'llm':{},'remote':{}},sys.argv[1])
"""
            child=subprocess.run([sys.executable,'-c',program,folder],
                                 cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=30)
            self.assertEqual(child.returncode,73,child.stderr)
            self.assertTrue((Path(folder)/'controller.lock').exists())
            self.assertFalse(any(e['kind']=='result' for e in ledger.events()))
            with patch('vision_rsi.controller.execute',return_value={'fixture':True}) as execute:
                research_step({'llm':{},'remote':{}},folder)
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['payload']['action'],'pending')
            client.assert_not_called()

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_active_os_lock_blocks_second_controller(self,client):
        from vision_rsi.campaign import lease
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            with lease(Path(folder)/'controller.lock'):
                with self.assertRaisesRegex(RuntimeError,'already active'):
                    research_step({'llm':{},'remote':{}},folder)
            self.assertEqual(len(ledger.events()),1)
            client.assert_not_called()

    def test_missing_key_does_not_leave_uncertain_planning_event(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'VISION_RSI_UNSET':''}), patch('vision_rsi.llm.urlopen') as http:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            config={'llm':{'model':'deepseek-flash','base_url':'https://example.invalid','api_key_env':'VISION_RSI_UNSET'},'remote':{}}
            with self.assertRaises(ValueError):research_step(config,folder)
            self.assertEqual(len(ledger.events()),1)
            http.assert_not_called()
    def test_no_arbitrary_tool_or_unknown_evidence(self):
        plan = {'tool':'shell','summary':'s','question':'q','expected_evidence':'e','refs':[]}
        import json
        with self.assertRaises(ValueError): parse_plan(json.dumps(plan), set())
        plan.update(tool='inspect_repository', refs=['missing'])
        with self.assertRaises(ValueError): parse_plan(json.dumps(plan), set())

    @patch('vision_rsi.controller.execute', return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_action_recovery_does_not_repeat_api(self, client, execute):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('request','evidence',{'summary':'request','record_type':'planning_request'})
            ledger.append('response','evidence',{'summary':'response','record_type':'planning_response',
                'request_key':'request','response':{'content':'{"tool":"inspect_repository","summary":"inspect","question":"q","expected_evidence":"e","refs":["goal"]}'}})
            result=research_step({'llm':{},'remote':{}},folder)
            client.assert_not_called()
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['kind'],'result')
            ledger.append('pause','paused',{'summary':'pause'})
            research_step({'llm':{},'remote':{}},folder)
            execute.assert_called_once()

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_uncertain_request_never_retries(self, client):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('request','evidence',{'summary':'request','record_type':'planning_request'})
            with self.assertRaises(RuntimeError):
                research_step({'llm':{},'remote':{}},folder)
            client.assert_not_called()
