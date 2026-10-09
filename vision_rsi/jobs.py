"""Durable CPU job protocol, also executed on the Linux remote host."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate(request):
    workspace = request['workspace']
    if not PurePosixPath(workspace).is_absolute() or '..' in PurePosixPath(workspace).parts or workspace == '/':
        raise ValueError('An absolute dedicated workspace is required')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', request['job_id']):
        raise ValueError('Invalid job ID')


def process_identity(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
        if stat[0] == 'Z':
            return None
        return {'start_ticks': stat[19], 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, IndexError):
        return None


def worker(folder):
    folder = Path(folder)
    spec = json.loads((folder / 'spec.json').read_text())
    state = {'status': 'running', 'started_at': time.time(), 'worker_pid': os.getpid(),
             'synthetic': False, 'gpu_count': 0, 'process_identity': process_identity(os.getpid())}
    save(folder / 'state.json', state)
    process = None
    try:
        with (folder / 'output.log').open('ab', buffering=0) as log:
            environment = dict(os.environ, CUDA_VISIBLE_DEVICES='')
            process = subprocess.Popen(spec['argv'], cwd=folder, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True, env=environment)
            start = time.monotonic()
            reason = None
            while process.poll() is None:
                if (folder / 'cancel.request').exists():
                    reason = 'cancelled'
                elif time.monotonic() - start >= spec['timeout_seconds']:
                    reason = 'timed_out'
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(0.1)
            state.update(status=reason or ('completed' if process.returncode == 0 else 'failed'),
                         returncode=process.returncode)
    except Exception as error:
        state.update(status='failed', error=type(error).__name__)
    finally:
        state['finished_at'] = time.time()
        state['elapsed_seconds'] = state['finished_at'] - state['started_at']
        state['gpu_hours'] = 0
        save(folder / 'state.json', state)


def dispatch(request):
    validate(request)
    folder = Path(request['workspace']) / 'jobs' / request['job_id']
    action = request['action']
    if action == 'submit':
        spec = request['spec']
        if (not isinstance(spec['argv'], list) or not spec['argv'] or
                not all(isinstance(x, str) and x for x in spec['argv'])):
            raise ValueError('argv must be a nonempty list of strings')
        timeout = spec['timeout_seconds']
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise ValueError('CPU smoke jobs require timeout in (0, 300]')
        identity = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if not (folder / 'spec.json').exists():
                raise RuntimeError('Incomplete submission; inspect job, never automatically resubmit')
            existing = json.loads((folder / 'spec.json').read_text())
            if existing != spec:
                raise ValueError('Job ID already belongs to another spec')
            return {'job_id': request['job_id'], 'duplicate': True, 'spec_hash': identity}
        save(folder / 'spec.json', spec)
        source = folder / 'worker.py'
        source.write_text(request['worker_source'], encoding='utf-8')
        save(folder / 'state.json', {'status': 'queued', 'spec_hash': identity})
        with (folder / 'worker.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(source), '--worker', str(folder)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, close_fds=True)
        return {'job_id': request['job_id'], 'duplicate': False, 'spec_hash': identity}
    if not folder.is_dir():
        raise ValueError('Unknown job ID')
    if action == 'cancel':
        (folder / 'cancel.request').touch()
    if action in ('status', 'cancel'):
        state = json.loads((folder / 'state.json').read_text())
        if state['status'] == 'running':
            if process_identity(state['worker_pid']) != state.get('process_identity') or state.get('process_identity') is None:
                state['status'] = 'lost'
        return state
    if action == 'logs':
        path = folder / 'output.log'
        if not path.exists(): return {'log': ''}
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 16384))
            return {'log': stream.read().decode(errors='replace')}
    raise ValueError('Unknown action')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
    else:
        print(json.dumps(dispatch(json.load(sys.stdin))))
