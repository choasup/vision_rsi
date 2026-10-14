"""Persistent, bounded console operations. Workers outlive browser/server connections."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

from .runner import atomic_json

ACTIVE = {'queued', 'running', 'stopping'}
ARTIFACTS = {'report.json', 'model.json', 'trials.json', 'sample-input.json', 'sample-prediction.json'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Jobs:
    def __init__(self, root, sessions, harness_root, repository, config):
        self.root = Path(root).resolve() / 'jobs'
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions = str(Path(sessions).resolve())
        self.harness_root = str(Path(harness_root).resolve())
        self.repository = str(Path(repository).resolve())
        self.config = config
        self.lock = threading.Lock()

    def list(self):
        return sorted((read(p) for p in self.root.glob('*/job.json')),
                      key=lambda j: j['created_at'], reverse=True)

    def folder(self, job_id):
        if not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('Invalid job ID')
        folder = self.root / job_id
        if not (folder / 'job.json').is_file():
            raise ValueError('Unknown job')
        return folder

    def show(self, job_id):
        folder = self.folder(job_id)
        result = read(folder / 'job.json')
        log = folder / 'output.log'
        if log.exists():
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size - 64000))
                result['log'] = stream.read(64000).decode('utf-8', errors='replace')
        else:
            result['log'] = ''
        if (folder / 'result.json').exists():
            result['result'] = read(folder / 'result.json')
        result['artifacts'] = [name for name in sorted(ARTIFACTS) if (folder / 'experiment' / name).is_file()]
        return result

    def start(self, action, session=None, message=None, version=None):
        if action not in {'advance', 'reply', 'accept', 'reject', 'cpu-demo'}:
            raise ValueError('Unknown action')
        if action != 'cpu-demo' and not session:
            raise ValueError('Session required')
        task = session['task_id'] if session else '__cpu_demo__'
        with self.lock:
            if any(j['task_id'] == task and j['status'] in ACTIVE for j in self.list()):
                raise ValueError('该任务已有后台操作，请查看进度；不要重复提交。')
            job_id = uuid.uuid4().hex
            folder = self.root / job_id
            folder.mkdir(mode=0o700)
            record = {'job_id': job_id, 'task_id': task, 'session_id': session['session_id'] if session else None,
                      'action': action, 'status': 'queued', 'created_at': time.time()}
            request = {'action': action, 'session_id': record['session_id'], 'message': message,
                       'version': version, 'sessions': self.sessions, 'harness_root': self.harness_root,
                       'repository': self.repository, 'config': self.config}
            atomic_json(folder / 'request.json', request)
            (folder / 'request.json').chmod(0o600)
            atomic_json(folder / 'job.json', record)
            try:
                with (folder / 'worker.log').open('ab') as log:
                    child = subprocess.Popen([sys.executable, '-u', '-m', 'vision_rsi.console_jobs', 'supervise', str(folder)],
                                             cwd=self.repository, stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=log, start_new_session=True)
                # Reap without tying the worker lifetime to this server.
                threading.Thread(target=child.wait, daemon=True).start()
            except OSError as error:
                record.update(status='failed', error=str(error))
                atomic_json(folder / 'job.json', record)
                raise
            return record

    def stop(self, job_id):
        folder = self.folder(job_id)
        result = read(folder / 'job.json')
        if result['status'] in ACTIVE:
            (folder / 'stop').touch()
        return result


def execute(folder):
    from .contracts import Sessions
    from .harness_progress import run_until_blocked, advance, status
    from .training_cli import conversation_summary
    request = read(folder / 'request.json')
    action = request['action']
    if action == 'cpu-demo':
        from .cpu_experiment import run
        return run(folder / 'experiment')
    store = Sessions(request['sessions'])
    session = store.show(request['session_id'])
    config = request['config']
    root = request['harness_root']
    repository = request['repository']
    if action == 'reply':
        if session['versions']:
            from .intent import resolve
            decision = resolve(request['message'], session, config, root, conversation_summary(session), [])
            print(decision['reason'], flush=True)
            action = decision['action']
            if action in ('explain', 'stop'):
                return {'status': 'stopped' if action == 'stop' else 'explained', 'message': decision['reply']}
            if action == 'data':
                return {'status': 'blocked', 'message': '公开数据搜索和下载执行器尚未接通，请提供本地数据路径。'}
            if action in ('accept', 'reject'):
                request['version'] = session['versions'][-1]['version']
        else:
            action = 'clarify'
    if action == 'clarify':
        session = store.clarify(session['session_id'], config['llm'], request['message'])
        return {'status': session['status'], 'message': conversation_summary(session)}
    if action in ('accept', 'reject'):
        latest = session['versions'][-1] if session['versions'] else {}
        if not latest.get('review_required') or latest.get('version') != request['version']:
            raise ValueError('需求草案已变化，请刷新后重新核对。')
        session = getattr(store, action)(session['session_id'], request['version'])
        return {'status': session['status'], 'message': conversation_summary(session)}
    if action == 'status':
        return status(session, root)
    if action in ('generate', 'check'):
        return advance(session, config, root, repository, generate_backend=action == 'generate', check_backend=action == 'check')
    if action == 'advance':
        if not session['versions']:
            session = store.clarify(session['session_id'], config['llm'])
            from .contracts import interface_issues, task_questions
            latest = session['versions'][-1] if session['versions'] else {}
            contract = latest.get('contract', {})
            if session['pending_request'] or latest.get('review_required') or interface_issues(contract) or task_questions(contract):
                return {'status': 'blocked', 'message': conversation_summary(session)}
        result = run_until_blocked(session, config, root, repository, on_progress=lambda message: print(message, flush=True))
        from .harness_progress import summary
        result['message'] = summary(result)
        return result
    raise ValueError('Unsupported action')


def supervise(folder):
    record = read(folder / 'job.json')
    if (folder / 'stop').exists():
        record.update(status='stopped', message='已取消，未启动执行进程。', finished_at=time.time())
        atomic_json(folder / 'job.json', record)
        return
    record.update(status='running', started_at=time.time())
    atomic_json(folder / 'job.json', record)
    try:
        with (folder / 'output.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, '-u', '-m', 'vision_rsi.console_jobs', 'execute', str(folder)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            interrupted = None
            while child.poll() is None:
                if (folder / 'stop').exists() or time.time() - record['started_at'] > 3600:
                    interrupted = 'stopped' if (folder / 'stop').exists() else 'timed_out'
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                    except ProcessLookupError:
                        child.wait()
                    break
                time.sleep(.2)
        result = read(folder / 'result.json') if (folder / 'result.json').exists() else {}
        record.update(status=interrupted or ('completed' if child.returncode == 0 else 'failed'),
                      exit_code=child.returncode, finished_at=time.time())
        if not interrupted and child.returncode == 0 and (str(result.get('status', '')).startswith('blocked') or result.get('status') in {'remote_required', 'generation_prerequisite_missing', 'generation_failed', 'generation_not_dispatched', 'generation_uncertain', 'smoke_uncertain', 'smoke_failed', 'interface_check_failed', 'repair_limit_reached'}):
            record['status'] = 'blocked'
        if interrupted:
            record['message'] = '本地操作已停止；远端请求或作业可能仍在运行，需查询原记录，不能据此自动重试。'
    except Exception as error:
        record.update(status='failed', error=str(error), finished_at=time.time())
    atomic_json(folder / 'job.json', record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['supervise', 'execute'])
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    if args.mode == 'supervise':
        supervise(args.folder)
    else:
        try:
            result = execute(args.folder)
        except Exception as error:
            atomic_json(args.folder / 'result.json', {'status': 'failed', 'message': '本次操作未完成，已有需求与进度已保留。请查看高级日志中的具体原因，修复后再继续。', 'error_type': type(error).__name__, 'detail': str(error)})
            raise
        atomic_json(args.folder / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
