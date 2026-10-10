import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.controller import planning_limit, research_step
from vision_rsi.ledger import Ledger


class PlanningBudgetTests(unittest.TestCase):
    def test_observation_prioritizes_recovery_over_exhaustion(self):
        from vision_rsi.research_state import snapshot
        def event(key,kind,**payload):return {'key':key,'kind':kind,'payload':payload}
        events=[event('goal','objective'),event('budget','evidence',record_type='planning_budget',max_planning_requests=1),
                event('request','evidence',record_type='planning_request')]
        self.assertEqual(snapshot(events)['state'],'uncertain_api_request')
        events.append(event('response','evidence',record_type='planning_response',request_key='request'))
        self.assertEqual(snapshot(events)['state'],'cached_response_available')
        events.append(event('action','action',executor='research-v1',planning_response='response'))
        self.assertEqual(snapshot(events)['state'],'pending_action_recovery')
        events.append(event('result','result',action='action'))
        self.assertEqual(snapshot(events)['state'],'planning_limit_exhausted')
        events.append(event('pause','paused'))
        self.assertEqual(snapshot(events)['state'],'paused')
        self.assertFalse(snapshot(events)['live_process_verified'])

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

