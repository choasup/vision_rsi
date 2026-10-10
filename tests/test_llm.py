import io
import json
import unittest
from unittest.mock import patch
from vision_rsi.llm import OpenAICompatibleClient


class LLMTests(unittest.TestCase):
    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_configuration_preflight_has_no_network_side_effect(self,opened):
        self.assertIsNone(self.client.validate_config())
        for changed in ({'base_url':'http://example.invalid'},{'base_url':'https://'},
                        {'base_url':'https://user:fixture@example.invalid'},
                        {'base_url':'https://example.invalid:bad'},{'model':''}):
            with self.subTest(config=changed),self.assertRaises(ValueError):
                OpenAICompatibleClient(dict(self.client.config,**changed)).validate_config()
        opened.assert_not_called()

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
