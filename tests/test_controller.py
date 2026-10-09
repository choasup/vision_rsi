import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.controller import parse_plan, research_step
from vision_rsi.ledger import Ledger


class ControllerTests(unittest.TestCase):
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
