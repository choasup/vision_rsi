"""Replaceable OpenAI-compatible client; credentials are never persisted."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class OpenAICompatibleClient:
    def __init__(self, config):
        self.config = config

    def complete(self, messages, max_tokens=128):
        key = os.environ.get(self.config['api_key_env'])
        if not key:
            raise ValueError('API key environment variable is missing')
        base = self.config['base_url'].rstrip('/')
        if not base.startswith('https://'):
            raise ValueError('LLM base_url must use HTTPS')
        payload = {'model': self.config['model'], 'messages': messages,
                   'max_tokens': max_tokens, 'stream': False}
        if 'thinking' in self.config:
            payload['thinking'] = {'type': self.config['thinking']}
        request = Request(base + '/chat/completions',
                          data=json.dumps(payload).encode(),
                          headers={'Authorization': 'Bearer ' + key,
                                   'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=60) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f'LLM HTTP {error.code}; response body suppressed') from None
        except (URLError, TimeoutError):
            raise RuntimeError('LLM network error or timeout') from None
        return {'model': result.get('model'),
                'content': result['choices'][0]['message']['content'],
                'usage': result.get('usage', {})}
