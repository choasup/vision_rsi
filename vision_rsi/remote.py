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
