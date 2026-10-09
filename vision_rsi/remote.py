"""Read-only SSH environment inspection. No remote installation or training."""
import json
import re
import shlex
import subprocess

PROBE = r'''
import importlib.util, json, platform, shutil, subprocess, sys
from pathlib import Path

def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return {'returncode': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'error': type(e).__name__}

roots = ['/run/ti', '/home/tione/notebook', '/home/tione/notebook/data', '/data']
report = {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
          'packages': {m: bool(importlib.util.find_spec(m)) for m in ['torch', 'torchvision', 'pycocotools']},
          'gpu': command(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.used,utilization.gpu', '--format=csv,noheader']),
          'disks': {}, 'directories': {}}
for root in roots:
    p = Path(root)
    if p.exists():
        usage = shutil.disk_usage(p)
        report['disks'][root] = {'total_bytes': usage.total, 'free_bytes': usage.free}
        try: report['directories'][root] = sorted(x.name for x in p.iterdir() if x.is_dir())
        except OSError: report['directories'][root] = []
print(json.dumps(report))
'''


def ssh_argv(remote):
    host = remote.get('ssh_host', '')
    port = remote.get('ssh_port', 22)
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
        raise ValueError('Invalid SSH host or alias')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Invalid SSH port')
    return ['ssh', '-p', str(port), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'StrictHostKeyChecking=yes', host]


def probe(remote):
    executable = remote.get('python', 'python3')
    result = subprocess.run(ssh_argv(remote) + [shlex.quote(executable) + ' -'],
                            input=PROBE, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('SSH probe failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout)


def job_request(remote, action, job_id, spec=None):
    from pathlib import Path
    import base64
    source = Path(__file__).with_name('jobs.py').read_text(encoding='utf-8-sig')
    request = {'workspace': remote.get('workspace', ''), 'action': action, 'job_id': job_id}
    if spec is not None:
        request.update(spec=spec, worker_source=source)
    # Keep all request data on stdin; only the fixed program is encoded in the command.
    encoded = base64.b64encode(source.encode()).decode()
    program = "import base64; exec(compile(base64.b64decode('" + encoded + "'), '<remote-jobs>', 'exec'))"
    executable = shlex.quote(remote.get('python', 'python3'))
    result = subprocess.run(ssh_argv(remote) + [executable + ' -c ' + shlex.quote(program)],
                            input=json.dumps(request), capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Remote job request failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout)


def detector_request(remote, action):
    from pathlib import Path
    import base64
    if action not in ('smoke','dataset-check'): raise ValueError('Unknown detector action')
    source=Path(__file__).with_name('detector.py').read_text(encoding='utf-8-sig')
    encoded=base64.b64encode(source.encode()).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<detector-adapter>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps({'action':action,'coco_root':remote.get('coco_root','')}),
                          capture_output=True,text=True,timeout=120)
    if result.returncode: raise RuntimeError('Detector adapter failed: '+result.stderr[-2000:])
    return json.loads(result.stdout)
