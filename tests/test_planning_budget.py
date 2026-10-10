import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.controller import planning_limit, research_step
from vision_rsi.ledger import Ledger


class PlanningBudgetTests(unittest.TestCase):
    def test_invalid_limits(self):
        for value in (None, True, 1.5, 0, 1001, '20'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                planning_limit({'research': {'max_planning_requests': value}}, [])

    def test_legacy_limit_cannot_expand(self):
        events = [{'payload': {'record_type': 'planning_request'}}]
        self.assertEqual(planning_limit({}, events), 6)
        with self.assertRaises(ValueError):
            planning_limit({'research': {'max_planning_requests': 20}}, events)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_restart_inherits_frozen_limit_and_stops(self, client):
        # Invalid responses consume attempts without executing any tool.
        client.return_value.complete.return_value = {'content': '{}'}
        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(folder)
            ledger.append('goal', 'objective', {'summary': 'bounded research'})
            config = {'llm': {'model': 'fixture'}, 'research': {'max_planning_requests': 2}}
            research_step(config, folder)
            research_step({'llm': {'model': 'fixture'}}, folder)
            research_step({'llm': {'model': 'fixture'}}, folder)
            self.assertEqual(client.return_value.complete.call_count, 2)
            events = ledger.events()
            self.assertEqual(len([e for e in events if e['payload'].get('record_type') == 'planning_budget']), 1)
            with self.assertRaises(ValueError):
                research_step(dict(config, research={'max_planning_requests': 3}), folder)
            self.assertEqual(len(ledger.events()), len(events))

