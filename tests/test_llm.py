import io
import json
import unittest
import threading
import subprocess
import time
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request
from urllib.error import HTTPError
from unittest.mock import patch
from vision_rsi.llm import OpenAICompatibleClient, NoRedirect, urlopen, _direct_open


class LLMTests(unittest.TestCase):
    @patch.dict('os.environ', {'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_optional_json_response_mode_is_transmitted_and_invalid_mode_never_sends(self,opened):
        opened.return_value.__enter__.return_value=io.StringIO(json.dumps({'model':'fixture','choices':[{'message':{'content':'{}'}}]}))
        client=OpenAICompatibleClient(dict(self.client.config,response_format='json_object'))
        client.complete([{'role':'user','content':'Return JSON'}])
        self.assertEqual(json.loads(opened.call_args.args[0].data)['response_format'],{'type':'json_object'})
        opened.reset_mock()
        for invalid in (None,{},True,'text'):
            with self.assertRaises(ValueError):OpenAICompatibleClient(dict(self.client.config,response_format=invalid)).validate_config()
        opened.assert_not_called()

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_configuration_preflight_has_no_network_side_effect(self,opened):
        self.assertIsNone(self.client.validate_config())
        for changed in ({'base_url':'http://example.invalid'},{'base_url':'https://'},
                        {'base_url':'https://user:fixture@example.invalid'},
                        {'base_url':'https://example.invalid?token=fixture'},
                        {'base_url':'https://example.invalid#fragment'},
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

    def test_redirect_handler_never_copies_credentials(self):
        request=Request('https://example.invalid/chat/completions',data=b'{}',headers={'Authorization':'Bearer fixture-secret'})
        handler=NoRedirect()
        for code in (301,302,303,307,308):
            for target in ('https://other.invalid/collect','http://example.invalid/collect','https://example.invalid/new'):
                self.assertIsNone(handler.redirect_request(request,None,code,'redirect',{},target))

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_invalid_output_limits_never_send_a_paid_request(self, opened):
        for limit in (True,False,None,0,-1,1.5,'128',32769,float('inf'),float('nan')):
            with self.subTest(limit=limit),self.assertRaisesRegex(ValueError,'max_tokens'):
                self.client.complete([],max_tokens=limit)
        opened.assert_not_called()

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_oversized_request_is_rejected_before_network(self, opened):
        with patch('vision_rsi.llm.MAX_REQUEST_BYTES',100):
            with self.assertRaisesRegex(ValueError,'request exceeds byte limit'):
                self.client.complete([{'role':'user','content':'long input'*100}])
        opened.assert_not_called()

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_response_size_is_bounded_and_closes_without_retry(self, opened):
        with patch('vision_rsi.llm.MAX_RESPONSE_BYTES', 64):
            body=io.BytesIO(b'x'*1000)
            opened.return_value.__enter__.return_value=body
            with self.assertRaisesRegex(RuntimeError,'byte limit'):
                self.client.complete([])
            self.assertEqual(body.tell(),65)
            opened.assert_called_once()
            opened.return_value.__exit__.assert_called_once()

    @patch.dict('os.environ', {'TEST_LLM_KEY': 'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_invalid_response_does_not_echo_body_or_retry(self, opened):
        cases=[b'fixture-secret invalid JSON', b'\xfffixture-secret', b'null',
               b'[]', b'{}', b'{"choices":[]}',
               json.dumps({'choices':[{'message':{'content':None}}]}).encode(),
               json.dumps({'choices':[{'message':{'content':'ok'}}],'usage':[]}).encode()]
        for raw in cases:
            opened.reset_mock()
            opened.return_value.__enter__.return_value=io.BytesIO(raw)
            with self.subTest(raw=raw),self.assertRaises(RuntimeError) as error:
                self.client.complete([])
            self.assertNotIn('fixture-secret',str(error.exception))
            opened.assert_called_once()
            opened.return_value.__exit__.assert_called_once()

    @patch('vision_rsi.llm.build_opener')
    def test_transport_installs_nonredirecting_handler(self,build):
        request=Request('https://example.invalid')
        _direct_open(request,timeout=60)
        self.assertIsInstance(build.call_args.args[0],NoRedirect)
        build.return_value.open.assert_called_once_with(request,timeout=60)

    @patch.dict('os.environ', {'NO_PROXY':'127.0.0.1'})
    def test_total_deadline_kills_real_slow_body_worker_without_retry(self):
        seen=[];sent=[];children=[]
        class Slow(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append('request')
                self.send_response(200)
                self.send_header('Content-Length','1000');self.end_headers()
                try:
                    for _ in range(1000):
                        self.wfile.write(b'x');self.wfile.flush();sent.append(1)
                        time.sleep(.05)
                except (OSError,ConnectionError):pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Slow)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        thread.start();original=subprocess.Popen
        def spawn(*args,**kwargs):
            child=original(*args,**kwargs);children.append(child);return child
        try:
            request=Request(f'http://127.0.0.1:{server.server_port}/chat',data=b'{}')
            started=time.monotonic()
            with patch('vision_rsi.llm.subprocess.Popen',side_effect=spawn):
                with self.assertRaisesRegex(TimeoutError,'total transport deadline'):
                    urlopen(request,timeout=1)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(seen,['request']);self.assertGreater(len(sent),1)
            self.assertEqual(len(children),1);self.assertIsNotNone(children[0].poll())
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    @patch.dict('os.environ', {'NO_PROXY':'127.0.0.1'})
    def test_real_worker_returns_body_and_closes(self):
        class Success(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Success)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        thread.start()
        try:
            request=Request(f'http://127.0.0.1:{server.server_port}/chat',data=b'{}')
            with urlopen(request,timeout=3) as response:
                self.assertEqual(json.load(response),{'ok':True})
            self.assertTrue(response.closed)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    @patch.dict('os.environ', {'NO_PROXY':'127.0.0.1'})
    def test_worker_own_deadline_does_not_depend_on_parent_cancellation(self):
        received=threading.Event();release=threading.Event()
        class Hang(BaseHTTPRequestHandler):
            def do_POST(self):received.set();release.wait(3)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Hang)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        thread.start()
        try:
            import vision_rsi.llm as llm
            request={'url':f'http://127.0.0.1:{server.server_port}/chat','data':'e30=',
                     'headers':{},'timeout':.5}
            result=subprocess.run([sys.executable,str(Path(llm.__file__).with_name('_llm_worker.py'))],
                                  input=json.dumps(request).encode(),capture_output=True,timeout=3)
            self.assertTrue(received.is_set());self.assertEqual(result.returncode,124)
            self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')
        finally:
            release.set();server.shutdown();server.server_close();thread.join(timeout=2)

    @patch.dict('os.environ', {'NO_PROXY':'127.0.0.1'})
    def test_actual_loopback_redirect_does_not_reach_other_origin(self):
        seen=[]
        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        sink=ThreadingHTTPServer(('127.0.0.1',0),Sink)
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header('Location',f'http://127.0.0.1:{sink.server_port}/sink')
                self.end_headers()
            def log_message(self,*args):pass
        source=ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        threads=[threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True) for server in (sink,source)]
        for thread in threads:thread.start()
        try:
            request=Request(f'http://127.0.0.1:{source.server_port}/chat',data=b'{}',headers={'Authorization':'Bearer fixture-secret'})
            with self.assertRaises(HTTPError) as error:urlopen(request,timeout=3)
            self.assertEqual(error.exception.code,302);error.exception.close()
            self.assertEqual(seen,[])
        finally:
            for server in (source,sink):server.shutdown();server.server_close()
            for thread in threads:thread.join(timeout=2)

    @patch.dict('os.environ', {'TEST_LLM_KEY':'fixture-secret'})
    @patch('vision_rsi.llm.urlopen')
    def test_redirect_error_is_suppressed_and_not_retried(self,opened):
        body=io.BytesIO(b'fixture-secret response body')
        opened.side_effect=HTTPError('https://other.invalid',302,'redirect',{},body)
        with self.assertRaises(RuntimeError) as error:self.client.complete([{'role':'user','content':'hi'}])
        self.assertNotIn('fixture-secret',str(error.exception))
        opened.assert_called_once();self.assertTrue(body.closed)
