"""Transactional research event ledger, independent of task and model provider."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

KINDS = {'objective', 'evidence', 'hypothesis', 'action', 'result', 'reflection', 'self_change', 'paused', 'resumed'}


class Ledger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'research.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            with connection:
                yield connection
        finally:
            connection.close()

    def events(self):
        with self.connect() as db:
            return self._events(db)

    @staticmethod
    def _events(db):
        return [{'seq': seq, 'key': key, 'kind': kind, 'payload': json.loads(payload), 'created_at': timestamp}
                for seq, key, kind, payload, timestamp in db.execute('SELECT * FROM events ORDER BY seq')]

    def append(self, key, kind, payload):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError('Event key must be 1..200 characters')
        if kind not in KINDS or not isinstance(payload, dict):
            raise ValueError('Invalid event type or payload')
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 100000:
            raise ValueError('Event too large')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT seq,kind,payload FROM events WHERE event_key=?', (key,)).fetchone()
            if existing:
                if existing[1:] != (kind, encoded):
                    raise ValueError('Idempotency key conflicts with another event')
                return existing[0]
            events = self._events(db)
            if not events and kind != 'objective':
                raise ValueError('Create objective first')
            if kind == 'objective' and events:
                raise ValueError('Objective is immutable; create a new research directory')
            if not isinstance(payload.get('summary'), str) or not payload['summary'].strip():
                raise ValueError('A nonempty decision summary is required')
            known = {e['key']: e for e in events}
            refs = payload.get('refs', [])
            if not isinstance(refs, list) or not all(isinstance(r, str) and r in known for r in refs):
                raise ValueError('Unknown evidence or action reference')
            if kind == 'result':
                if payload.get('action') not in known or known[payload['action']]['kind'] != 'action':
                    raise ValueError('Result must reference an existing action')
                if any(e['kind'] == 'result' and e['payload']['action'] == payload['action'] for e in events):
                    raise ValueError('Action already has a result')
                if payload.get('status') not in ('completed', 'failed', 'cancelled', 'timed_out', 'lost'):
                    raise ValueError('Invalid terminal action status')
            if kind == 'self_change' and payload.get('status') != 'proposed':
                raise ValueError('Self changes remain proposals; promotion is not implemented')
            controls = [e['kind'] for e in events if e['kind'] in ('paused', 'resumed')]
            paused = bool(controls and controls[-1] == 'paused')
            if kind == 'paused' and paused or kind == 'resumed' and not paused:
                raise ValueError('Invalid pause/resume transition')
            if paused and kind in ('hypothesis', 'action', 'self_change'):
                raise ValueError('Research is paused; resume before adding new work')
            cursor = db.execute('INSERT INTO events(event_key,kind,payload,created_at) VALUES (?,?,?,?)',
                                (key, kind, encoded, datetime.now(timezone.utc).isoformat()))
            return cursor.lastrowid


def import_demo(ledger, source):
    path = Path(source)
    raw = path.read_bytes()
    demo = json.loads(raw)
    run = demo['run_id']
    ledger.append('objective', 'objective', {'summary': '构建可观测、可恢复的视觉长程研究 Agent；当前导入连通性 Demo 作为基础设施证据。', 'scope': 'vision research', 'limitations': '尚未自主研究或验证 RSI；导入指标为合成数据。'})
    ledger.append(run + ':source', 'evidence', {'summary': '已完成真实 DeepSeek 与 SSH 连通性实验。合成指标不作为检测或 RSI 提升证据。',
                  'source_path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_revision': demo['identity']['git_revision'], 'synthetic_metrics': True})
    for i, experiment in enumerate(demo['experiments']):
        prefix = run + ':' + str(i)
        ledger.append(prefix + ':hypothesis', 'hypothesis', {'summary': experiment['hypothesis'], 'refs': [run + ':source'],
                       'origin': 'fixed baseline' if i == 0 else 'DeepSeek', 'recipe': experiment['recipe']})
        ledger.append(prefix + ':action', 'action', {'summary': '远端执行 CPU 合成实验', 'refs': [prefix + ':hypothesis'],
                       'job_id': experiment['job_id'], 'command': experiment['spec']['argv'], 'timeout_seconds': experiment['spec']['timeout_seconds']})
        ledger.append(prefix + ':result', 'result', {'summary': '导入已执行任务的结果；指标是合成值。', 'action': prefix + ':action',
                       'status': experiment['status'], 'metric_value': experiment.get('metric_value'), 'synthetic': True,
                       'remote_result': experiment.get('remote_result'), 'log': experiment.get('remote_log', '')})
    ledger.append(run + ':reflection', 'reflection', {'summary': '执行连通性已验证，但当前候选范围窄，尚无视觉研究或自我改进能力证据。下一步接入开放研究行动及独立验证。',
                   'refs': [run + ':source'], 'llm_usage': [c.get('usage', {}) for c in demo['llm_calls']]})
    return ledger.events()
