import io
import json
import unittest
from unittest.mock import patch
from vision_rsi.llm import OpenAICompatibleClient


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenAICompatibleClient({'base_url': 'https://example.invalid',
            'model': 'fixture', 'api_key_env': 'TEST_LLM_KEY'})

    @patch.dict('os.environ', {}, clear=True)
    def test_missing_key(self):
        with self.assertRaises(ValueError):
            self.client.complete([])

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_request_and_usage(self, opened):
        opened.return_value.__enter__.return_value = io.StringIO(json.dumps({
            'model': 'fixture', 'choices': [{'message': {'content': 'OK'}}],
            'usage': {'total_tokens': 3}}))
        result = self.client.complete([{'role': 'user', 'content': 'Hi'}])
        self.assertEqual(result['usage']['total_tokens'], 3)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.invalid/chat/completions')
        self.assertEqual(json.loads(request.data)['model'], 'fixture')
        self.assertNotIn('fixture-secret', json.dumps(result))
