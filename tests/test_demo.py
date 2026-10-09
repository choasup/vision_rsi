import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.demo import demo, parse_proposal
from vision_rsi.research import evaluate, fingerprint


class DemoTests(unittest.TestCase):
    def test_proposal_whitelist(self):
        for value in [True, -1, 9, '1', 0]:
            with self.assertRaises(ValueError):
                parse_proposal(json.dumps({'candidate_index':value,'hypothesis':'test'}), [1,2])
        self.assertEqual(parse_proposal('{"candidate_index":1,"hypothesis":"test"}', [1,2])[0], 1)

    @patch('vision_rsi.demo.revision', return_value='fixture')
    @patch('vision_rsi.demo.OpenAICompatibleClient')
    @patch('vision_rsi.demo.job_request')
    def test_live_protocol_resume_does_not_repeat_llm(self, remote, client, _):
        recipes = {}
        def request(config, action, job_id, spec=None):
            if action == 'submit':
                import ast
                code = spec['argv'][-1]
                recipes[job_id] = ast.literal_eval(code.split('recipe=',1)[1].split(';',1)[0])
                return {'duplicate': job_id in recipes}
            if action == 'status':
                return {'status':'completed','gpu_hours':0}
            recipe = recipes[job_id]
            return {'log':json.dumps({'synthetic':True, 'recipe_hash':fingerprint(recipe),
                                     'metric_value':evaluate(recipe,42)})}
        remote.side_effect = request
        client.return_value.complete.side_effect = [
            {'content':json.dumps({'candidate_index':i,'hypothesis':'test'}), 'usage':{'total_tokens':10}}
            for i in [1,4]]
        with tempfile.TemporaryDirectory() as folder:
            first = demo({'remote':{},'llm':{}}, folder)
            self.assertEqual(first['experiments'], 3)
            self.assertEqual(client.return_value.complete.call_count, 2)
            before = remote.call_count
            demo({'remote':{},'llm':{}}, folder)
            self.assertEqual(remote.call_count, before)
            path = Path(folder)/'demo-state.json'
            state=json.loads(path.read_text())
            del state['experiments'][-1]['metric_value']
            path.write_text(json.dumps(state))
            demo({'remote':{},'llm':{}}, folder)
            self.assertIn('metric_value',json.loads(path.read_text())['experiments'][-1])
            self.assertEqual(client.return_value.complete.call_count, 2)
            self.assertIn('合成', (Path(folder)/'report.html').read_text(encoding='utf-8'))
