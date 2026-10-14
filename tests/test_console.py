import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from vision_rsi.console import make_server
from vision_rsi.contracts import Sessions
from vision_rsi.console_jobs import Jobs, ACTIVE


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = make_server(self.root / 'console', {'llm': {}}, 0, sessions_root=self.root / 'sessions')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.address = 'http://127.0.0.1:' + str(self.server.server_address[1])

    def request(self, path, data=None, token=True, extra=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Agent-Token'] = self.server.agent_token
        headers.update(extra or {})
        with urlopen(Request(self.address + path, data=json.dumps(data).encode() if data is not None else None,
                             headers=headers), timeout=5) as response:
            return json.load(response)

    def wait(self, job):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = self.request('/api/jobs/' + job['job_id'])
            if result['status'] not in ACTIVE:
                return result
            time.sleep(.1)
        self.fail('Worker did not finish: ' + str(result))

    def test_same_task_reuses_cli_ledger_and_request_boundaries(self):
        for path in ('/api/tasks', '/api/jobs'):
            with self.assertRaises(HTTPError):
                self.request(path, token=False)
        with self.assertRaises(HTTPError):
            self.request('/api/demo', {}, extra={'Origin': 'https://other.example'})
        with self.assertRaises(HTTPError):
            self.request('/api/tasks', [])
        created = self.request('/api/tasks', {'task_id': 'catdog', 'goal': '猫狗分类'})
        reopened = self.request('/api/tasks', {'task_id': 'catdog', 'goal': '不会覆盖'})
        self.assertEqual(created['session_id'], reopened['session_id'])
        self.assertEqual(len(Sessions(self.root / 'sessions').list()), 1)
        self.assertEqual(reopened['turns'][0]['content'], '猫狗分类')
        detail = self.request('/api/tasks/' + created['session_id'])
        self.assertFalse(detail['training_started'])
        self.assertTrue(self.request('/api/health')['execution_enabled'])
        self.assertFalse(self.request('/api/health')['general_training_enabled'])

    def test_missing_model_reports_failure_and_preserves_task(self):
        session = self.request('/api/tasks', {'task_id': 'catdog', 'goal': '猫狗分类'})
        job = self.request('/api/tasks/' + session['session_id'] + '/reply', {'message': '先跑基线'})
        result = self.wait(job)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Error', result['log'])
        self.assertEqual(len(self.request('/api/tasks')), 1)
        self.assertEqual(self.request('/api/health')['status'], 'ready')

    @unittest.skipUnless(importlib.util.find_spec('sklearn'), 'Requires cpu extra')
    def test_actual_cpu_run_duplicate_guard_reconnect_and_artifacts(self):
        job = self.request('/api/demo', {})
        with self.assertRaises(HTTPError):
            self.request('/api/demo', {})
        # A fresh manager reads the same durable operation; no new worker needed.
        reopened = Jobs(self.root / 'console', self.root / 'sessions', self.root / 'harness', '.', {})
        self.assertEqual(reopened.show(job['job_id'])['job_id'], job['job_id'])
        result = self.wait(job)
        self.assertEqual(result['status'], 'completed', result['log'])
        self.assertTrue(result['result']['training_performed'])
        self.assertGreater(result['result']['test_accuracy'], .9)
        self.assertEqual(result['result']['test_total'], 360)
        model = self.request('/api/jobs/' + job['job_id'] + '/artifacts/model.json')
        self.assertIsInstance(model, dict)
        with self.assertRaises(HTTPError):
            self.request('/api/jobs/' + job['job_id'] + '/artifacts/request.json')
        self.assertIn('C=1.0', result['log'])

    @unittest.skipUnless(importlib.util.find_spec('sklearn'), 'Requires cpu extra')
    def test_stop_terminates_local_worker_and_persists_state(self):
        job = self.request('/api/demo', {})
        self.request('/api/jobs/' + job['job_id'] + '/stop', {})
        result = self.wait(job)
        self.assertEqual(result['status'], 'stopped', result)
        self.assertIn('远端', result['message'])
