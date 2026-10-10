"""Replaceable OpenAI-compatible client; credentials are never persisted."""
import json
import os
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Default urllib copies Authorization to redirected requests, including
        # another host. Require the configured HTTPS endpoint to answer directly.
        return None


def urlopen(request, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


class OpenAICompatibleClient:
    def __init__(self, config):
        self.config = config

    def validate_config(self):
        env_name=self.config.get('api_key_env')
        if not isinstance(env_name,str) or not env_name or not os.environ.get(env_name):
            raise ValueError('API key environment variable is missing')
        base=self.config.get('base_url')
        if not isinstance(base,str):raise ValueError('LLM base_url must use HTTPS')
        parts=urlsplit(base)
        if parts.scheme!='https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError('LLM base_url must use HTTPS')
        parts.port  # Validate port syntax before reserving any caller budget.
        if not isinstance(self.config.get('model'),str) or not self.config['model'].strip():raise ValueError('LLM model ID is missing')

    def complete(self, messages, max_tokens=128):
        self.validate_config()
        key = os.environ[self.config['api_key_env']]
        base = self.config['base_url'].rstrip('/')
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
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw.encode('utf-8') if isinstance(raw, str) else raw) > MAX_RESPONSE_BYTES:
                    raise RuntimeError('LLM response exceeds byte limit; body suppressed')
        except HTTPError as error:
            code=error.code
            error.close()
            raise RuntimeError(f'LLM HTTP {code}; response body suppressed') from None
        except (URLError, TimeoutError):
            raise RuntimeError('LLM network error or timeout') from None
        try:
            result = json.loads(raw)
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            model = result.get('model')
            if not isinstance(content, str) or not isinstance(usage, dict):
                raise ValueError('Invalid completion shape')
            if model is not None and not isinstance(model, str):
                raise ValueError('Invalid model identity')
        except (ValueError, UnicodeError, KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError('LLM response is invalid; body suppressed') from None
        return {'model': model, 'content': content, 'usage': usage}
