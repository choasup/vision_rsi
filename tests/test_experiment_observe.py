import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from vision_rsi.experiment_observe import inspect_request
from vision_rsi.runner import digest


class ExperimentObserveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'requests.sqlite3'

    def write(self, state='responded', legacy=False, tamper=False):
        snapshot = {'messages': [{'role': 'user', 'content': 'synthetic observation'}],
                    'max_tokens': 2048, 'remaining_gpu_hours_snapshot': .5}
        context = {'run_id': 'run1', 'parent_plan_id': 'plan1', 'receipt_sha256': 'fixture'}
        if not legacy:
            context.update(request_snapshot=snapshot, request_snapshot_sha256=digest(snapshot))
            if tamper:
                snapshot['max_tokens'] = 1
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,context TEXT,state TEXT,response TEXT)')
            db.execute('INSERT INTO requests VALUES (?,?,?,?)', ('one', json.dumps(context), state,
                       json.dumps({'content': 'synthetic reply'}) if state == 'responded' else None))
            db.commit()

    def test_read_only_summary_and_explicit_messages(self):
        self.write()
        before = self.path.read_bytes()
        summary = inspect_request(self.root, 'one')
        self.assertTrue(summary['snapshot_hash_verified'])
        self.assertNotIn('response', summary)
        self.assertNotIn('request_snapshot', summary)
        self.assertEqual(summary['remaining_gpu_hours_snapshot'], .5)
        full = inspect_request(self.root, 'one', True)
        self.assertEqual(full['response']['content'], 'synthetic reply')
        self.assertEqual(before, self.path.read_bytes())

    def test_reserved_request_is_observable_without_retry(self):
        self.write(state='reserved')
        report = inspect_request(self.root, 'one', True)
        self.assertFalse(report['automatic_retry_allowed'])
        self.assertIsNone(report['response'])
        self.assertTrue(report['snapshot_hash_verified'])

    def test_legacy_no_snapshot_is_not_invented(self):
        self.write(legacy=True)
        report = inspect_request(self.root, 'one')
        self.assertFalse(report['snapshot_available'])
        self.assertFalse(report['snapshot_hash_verified'])
        self.assertIsNone(report['remaining_gpu_hours_snapshot'])

    def test_tamper_rejected(self):
        self.write(tamper=True)
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            inspect_request(self.root, 'one')

    def test_missing_store_and_unknown_request_do_not_create_files(self):
        missing = self.root / 'missing'
        with self.assertRaises(ValueError):
            inspect_request(missing, 'one')
        self.assertFalse(missing.exists())
        self.write()
        for key in ('unknown', '../one'):
            with self.assertRaises(ValueError):
                inspect_request(self.root, key)

    def test_actual_cli(self):
        self.write(state='not_dispatched')
        result = subprocess.run([sys.executable, '-m', 'vision_rsi', 'experiment-request',
                                 '--store', str(self.root), '--request-id', 'one', '--messages'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'not_dispatched')
