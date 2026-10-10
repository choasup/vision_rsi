"""Replaceable OpenAI-compatible client; credentials are never persisted."""
import json
import os
import base64
import io
import math
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_TOKENS = 32768


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Default urllib copies Authorization to redirected requests, including
        # another host. Require the configured HTTPS endpoint to answer directly.
        return None


def _direct_open(request, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def urlopen(request, timeout):
    """Bound connection, headers and body together; never retry an uncertain call."""
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('LLM transport timeout must be in (0,60]')
    payload=json.dumps({'url':request.full_url,'headers':dict(request.header_items()),
                        'data':None if request.data is None else base64.b64encode(request.data).decode(),
                        'timeout':timeout}).encode()
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('_llm_worker.py'))],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                             creationflags=flags)
    try:
        output,_=process.communicate(payload,timeout=timeout)
    except BaseException as error:
        process.kill()
        process.communicate()
        if isinstance(error,subprocess.TimeoutExpired):
            raise TimeoutError('LLM total transport deadline exceeded') from None
        raise
    if process.returncode==124:
        raise TimeoutError('LLM total transport deadline exceeded')
    if process.returncode or len(output)>MAX_RESPONSE_BYTES+100:
        raise RuntimeError('LLM transport worker failed; body suppressed')
    header,separator,body=output.partition(b'\n')
    if separator and header==b'OK':return io.BytesIO(body)
    if separator and header.startswith(b'HTTP ') and header[5:].isdigit():
        raise HTTPError(request.full_url,int(header[5:]),'LLM HTTP error',{},io.BytesIO())
    if header==b'OVERSIZED':raise RuntimeError('LLM response exceeds byte limit; body suppressed')
    raise URLError('LLM transport worker failed')


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
        if 'usage_ledger' in self.config:
            from .llm_usage import ledger_path
            ledger_path(self.config['usage_ledger'])

    def complete(self, messages, max_tokens=128):
        self.validate_config()
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError('LLM max_tokens must be an integer in 1..32768')
        key = os.environ[self.config['api_key_env']]
        base = self.config['base_url'].rstrip('/')
        payload = {'model': self.config['model'], 'messages': messages,
                   'max_tokens': max_tokens, 'stream': False}
        if 'thinking' in self.config:
            payload['thinking'] = {'type': self.config['thinking']}
        encoded = json.dumps(payload).encode()
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError('LLM request exceeds byte limit')
        request = Request(base + '/chat/completions',
                          data=encoded,
                          headers={'Authorization': 'Bearer ' + key,
                                   'Content-Type': 'application/json'})
        ledger=None
        if 'usage_ledger' in self.config:
            from .llm_usage import UsageLedger
            ledger=UsageLedger(self.config['usage_ledger'])
            identity=ledger.reserve(encoded,self.config['model'])
        try:
            result=self._response(request)
        except BaseException:
            if ledger is not None:
                try:ledger.finish(identity)
                except Exception:pass  # Pending remains visibly unknown, never zero.
            raise
        if ledger is not None:
            ledger.finish(identity,result['usage'])
            result['usage_record_id']=identity
        return result

    def _response(self,request):
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
