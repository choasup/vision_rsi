"""Durable budgeted CPU/GPU job protocol, also executed on the Linux remote host."""
import hashlib
import json
import math
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


def validate_spec(spec):
    if not isinstance(spec,dict) or not isinstance(spec.get('argv'),list) or not spec['argv'] or not all(isinstance(x,str) and x and '\x00' not in x for x in spec['argv']):
        raise ValueError('argv must be a nonempty list of strings')
    timeout=spec.get('timeout_seconds')
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Finite positive timeout required')
    devices=spec.get('gpu_devices',[])
    if not isinstance(devices,list) or len(devices)>8 or any(isinstance(x,bool) or not isinstance(x,int) or not 0<=x<8 for x in devices) or len(devices)!=len(set(devices)):
        raise ValueError('gpu_devices must be unique H20 device indices 0..7')
    if devices:
        budget=spec.get('gpu_hours_budget')
        if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or budget<=0 or budget+1e-12<len(devices)*(timeout+5)/3600:
            raise ValueError('Explicit GPU budget must cover reserved GPUs times timeout plus 5s shutdown reserve')
        if timeout>30*24*3600: raise ValueError('GPU timeout exceeds 30 days')
    elif timeout>300:
        raise ValueError('CPU smoke jobs require timeout in (0, 300]')
    return devices


def reserve_devices(folder, devices):
    # flock leases survive worker death while inherited descriptors are held by
    # the launched process. Scope is this dedicated workspace, not host-global.
    import fcntl
    leases=[]
    root=folder.parent.parent/'gpu-leases';root.mkdir(exist_ok=True)
    try:
        for device in sorted(devices):
            lease=(root/f'gpu-{device}.lock').open('a+')
            leases.append(lease)
            try: fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('GPU device already reserved by an Agent job: '+str(device))
        return leases
    except Exception:
        for lease in leases: lease.close()
        raise


def terminate_group(process):
    try: os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        process.poll()  # Reap the leader so it cannot keep the group alive as zombie.
        try: os.killpg(process.pid,0)
        except ProcessLookupError: break
        time.sleep(.05)
    else:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    process.wait()


def worker(folder):
    folder = Path(folder)
    spec = json.loads((folder / 'spec.json').read_text())
    devices=validate_spec(spec)
    worker_start=time.monotonic()
    state = {'status': 'running', 'started_at': time.time(), 'worker_pid': os.getpid(),
             'synthetic': False, 'gpu_count': len(devices), 'gpu_devices': devices, 'process_identity': process_identity(os.getpid())}
    state['spec_hash']=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    state['worker_source_sha256']=hashlib.sha256((folder/'worker.py').read_bytes()).hexdigest()
    save(folder / 'state.json', state)
    process = None
    leases=[]
    stop_requested=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop_requested.__setitem__(0,True))
    try:
        if devices: leases=reserve_devices(folder,devices)
        with (folder / 'output.log').open('ab', buffering=0) as log:
            environment = dict(os.environ, CUDA_VISIBLE_DEVICES=','.join(map(str,devices)))
            process = subprocess.Popen(spec['argv'], cwd=folder, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True, env=environment,
                                       pass_fds=tuple(lease.fileno() for lease in leases))
            state.update(child_pid=process.pid,child_identity=process_identity(process.pid))
            save(folder/'state.json',state)
            start = time.monotonic()
            reason = None
            while process.poll() is None:
                if stop_requested[0] or (folder / 'cancel.request').exists():
                    reason = 'cancelled'
                elif time.monotonic() - start >= spec['timeout_seconds'] or (devices and time.monotonic()-worker_start >= spec['gpu_hours_budget']*3600/len(devices)-3):
                    reason = 'timed_out'
                if reason:
                    terminate_group(process)
                    break
                time.sleep(0.1)
            state.update(status=reason or ('completed' if process.returncode == 0 else 'failed'),
                         returncode=process.returncode)
    except Exception as error:
        state.update(status='failed', error=type(error).__name__+': '+str(error))
    finally:
        # End remaining ranks/children even if the launcher exited first.
        if process is not None: terminate_group(process)
        for lease in leases: lease.close()
        state['finished_at'] = time.time()
        state['elapsed_seconds'] = time.monotonic()-worker_start
        state['gpu_hours'] = len(devices)*state['elapsed_seconds']/3600
        state['gpu_hours_accounting']='reserved device count times worker wall time, including startup/cleanup'
        save(folder / 'state.json', state)


def dispatch(request):
    validate(request)
    folder = Path(request['workspace']) / 'jobs' / request['job_id']
    action = request['action']
    if action == 'submit':
        spec = request['spec']
        validate_spec(spec)
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
