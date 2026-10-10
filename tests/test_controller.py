import tempfile
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from vision_rsi.controller import parse_plan, research_step
from vision_rsi.ledger import Ledger


class ControllerTests(unittest.TestCase):
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
