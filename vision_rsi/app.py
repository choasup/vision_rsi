"""Local task application: persistent queue and live research event API."""
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .controller import research_step
from .ledger import Ledger


class TaskService:
    def __init__(self, root, config, repository):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config, self.repository = config, repository
        self.stop = threading.Event()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, request_key TEXT UNIQUE, objective TEXT, status TEXT, error TEXT, created REAL)')
            db.execute("UPDATE tasks SET status='interrupted',error='应用退出时任务尚未结束；检查后可继续。' WHERE status IN ('running','pause_requested')")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'tasks.sqlite3', timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def create(self, objective, request_key):
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
            raise ValueError('任务目标需为 1–4000 字符')
        if not isinstance(request_key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_key):
            raise ValueError('Invalid request key')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM tasks WHERE request_key=?', (request_key,)).fetchone()
            if old:
                if old['objective'] != objective: raise ValueError('请求 ID 冲突')
                return old['id']
            task_id = uuid.uuid4().hex
            ledger = Ledger(self.root / task_id)
            ledger.append('objective', 'objective', {'summary': objective, 'capability': '只读研究准备：源码检查、远端环境检查、证据总结；不训练或修改代码。'})
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)', (task_id, request_key, objective, 'queued', '', time.time()))
            return task_id

    def tasks(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY created DESC')]

    def ledger(self, task_id):
        if not re.fullmatch('[a-f0-9]{32}', task_id): raise ValueError('Invalid task ID')
        with self.db() as db:
            if not db.execute('SELECT id FROM tasks WHERE id=?', (task_id,)).fetchone(): raise ValueError('Unknown task')
        return Ledger(self.root / task_id)

    def control(self, task_id, action):
        self.ledger(task_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            status = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
            if action == 'pause' and status in ('queued', 'running'):
                new = 'paused' if status == 'queued' else 'pause_requested'
            elif action == 'resume' and status in ('paused', 'interrupted', 'failed'):
                new = 'queued'
            else: raise ValueError('当前状态不允许此操作')
            db.execute('UPDATE tasks SET status=?,error=? WHERE id=?', (new, '', task_id))

    def set_status(self, task_id, status, error=''):
        with self.db() as db:
            db.execute('UPDATE tasks SET status=?,error=? WHERE id=?', (status, error, task_id))

    def work(self):
        while not self.stop.is_set():
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                task = db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if task: db.execute("UPDATE tasks SET status='running' WHERE id=?", (task['id'],))
            if not task:
                self.stop.wait(0.5)
                continue
            task_id = task['id']
            ledger = self.ledger(task_id)
            try:
                # A lock remaining after a hard exit must be inspected, not silently removed.
                controls = [e['kind'] for e in ledger.events() if e['kind'] in ('paused', 'resumed')]
                if controls and controls[-1] == 'paused':
                    ledger.append('resume-' + uuid.uuid4().hex, 'resumed', {'summary': '用户通过应用继续任务。'})
                for _ in range(6):
                    with self.db() as db:
                        status = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
                    if status == 'pause_requested' or self.stop.is_set():
                        ledger.append('pause-' + uuid.uuid4().hex, 'paused', {'summary': '已在行动边界暂停；当前请求不会被强制中断。'})
                        self.set_status(task_id, 'paused')
                        break
                    before = len(ledger.events())
                    research_step(self.config, ledger.directory, repository=self.repository)
                    if len(ledger.events()) == before:
                        self.set_status(task_id, 'round_finished')
                        break
                else:
                    self.set_status(task_id, 'round_finished')
            except Exception as error:
                self.set_status(task_id, 'failed', type(error).__name__ + ': ' + str(error)[:1000])


def serve(config, directory, repository, port=8767):
    service = None
    token = secrets.token_urlsafe(32)
    page = Path(__file__).with_name('app.html').read_text(encoding='utf-8').replace('__TOKEN__', token)
    expected_host = f'127.0.0.1:{port}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, status, data, mime='application/json'):
            body = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Host') != expected_host: return self.send(403, {'error': 'Invalid host'})
            if self.path == '/': return self.send(200, page, 'text/html')
            if self.headers.get('X-Agent-Token') != token: return self.send(403, {'error': 'Invalid local token'})
            try:
                if self.path == '/api/tasks': return self.send(200, service.tasks())
                match = re.fullmatch('/api/tasks/([a-f0-9]{32})', self.path)
                if match: return self.send(200, service.ledger(match[1]).events())
                return self.send(404, {'error': 'Not found'})
            except ValueError as error: self.send(400, {'error': str(error)})
        def do_POST(self):
            if self.headers.get('Host') != expected_host or self.headers.get('X-Agent-Token') != token:
                return self.send(403, {'error': 'Invalid local request'})
            if self.headers.get('Origin') not in (None, 'http://' + expected_host):
                return self.send(403, {'error': 'Invalid origin'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 20000: raise ValueError('Invalid body size')
                value = json.loads(self.rfile.read(size))
                if self.path == '/api/tasks':
                    return self.send(200, {'id': service.create(value['objective'], value['request_key'])})
                match = re.fullmatch('/api/tasks/([a-f0-9]{32})/(pause|resume)', self.path)
                if match:
                    service.control(*match.groups())
                    return self.send(200, {'ok': True})
                self.send(404, {'error': 'Not found'})
            except (ValueError, KeyError, TypeError) as error: self.send(400, {'error': str(error)})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    service = TaskService(directory, config, repository)
    worker = threading.Thread(target=service.work, daemon=True)
    worker.start()
    print(f'Vision RSI Agent: http://{expected_host}', flush=True)
    try: server.serve_forever()
    finally:
        service.stop.set()
        server.server_close()
