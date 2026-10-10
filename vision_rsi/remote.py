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


def deploy_training(remote, plan):
    """Transfer only pinned Python sources, task contract and recipe; no secrets."""
    import base64
    import hashlib
    from pathlib import Path
    from .runner import digest
    files={}
    hashes={}
    parent=plan.get('parent_deployment')
    if parent:
        hashes={'vision_rsi/'+name:value for name,value in plan['source_hashes'].items()}
    else:
        for path in sorted(Path(__file__).parent.glob('*.py')):
            content=path.read_bytes();name='vision_rsi/'+path.name
            files[name]=base64.b64encode(content).decode()
            hashes[name]=hashlib.sha256(content).hexdigest()
        if {Path(name).name:value for name,value in hashes.items()}!=plan['source_hashes']:
            raise ValueError('Source changed after Training plan was prepared')
    identity={'sources':hashes,'recipe':plan['recipe'],'contract':plan['contract']}
    bundle_id=digest(identity)
    request={'workspace':remote['workspace'],'bundle_id':bundle_id,'files':files,
             'recipe':plan['recipe'],'contract':plan['contract']}
    if parent:request.update(parent_directory=parent,parent_sources=hashes)
    source=Path(__file__).with_name('deployment.py').read_bytes()
    encoded=base64.b64encode(source).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<training-deploy>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps(request),capture_output=True,text=True,timeout=60)
    if result.returncode: raise RuntimeError('Training deployment failed: '+result.stderr[-2000:])
    response=json.loads(result.stdout)
    if response.get('bundle_id')!=bundle_id: raise ValueError('Remote bundle identity mismatch')
    return response


def collect_training(remote,run_id,output_directory,output_run_id=None,action="collect"):
    import base64
    from pathlib import Path
    source=Path(__file__).with_name('artifacts.py').read_bytes()
    encoded=base64.b64encode(source).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<training-artifacts>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps({'workspace':remote['workspace'],'run_id':run_id,'output_run_id':output_run_id or run_id,'output_directory':output_directory,'action':action}),capture_output=True,text=True,timeout=90)
    if result.returncode: raise RuntimeError('Training collection failed: '+result.stderr[-2000:])
    response=json.loads(result.stdout)
    if response.get('run_id')!=run_id: raise ValueError('Collected wrong Training run')
    return response


def infer_training(remote,request,source_path):
    import base64
    from pathlib import Path
    source=Path(source_path).read_bytes()
    encoded=base64.b64encode(source).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<registered-inference>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps(dict(request,workspace=remote['workspace'])),capture_output=True,text=True,timeout=90)
    if result.returncode:raise RuntimeError('Remote inference failed: '+result.stderr[-2000:])
    return json.loads(result.stdout)


def serving_step(remote,endpoint,source_path,wall_seconds_budget,chunk_size=10):
    import base64,hashlib
    from pathlib import Path
    driver=Path(__file__).with_name('serving.py').read_bytes()
    adapter=Path(source_path).read_bytes()
    request={'workspace':remote['workspace'],'endpoint':{key:value for key,value in endpoint.items() if key!='remote'},
             'adapter_source_base64':base64.b64encode(adapter).decode(),'inference_adapter_sha256':hashlib.sha256(adapter).hexdigest(),
             'wall_seconds_budget':wall_seconds_budget,'chunk_size':chunk_size}
    encoded=base64.b64encode(driver).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<serving-evaluation>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps(request),capture_output=True,text=True,timeout=330)
    if result.returncode:raise RuntimeError('Serving evaluation failed: '+result.stderr[-2000:])
    return json.loads(result.stdout)


def check_candidate(remote,request):
    import base64
    from pathlib import Path
    source=Path(__file__).with_name('candidate_runtime.py').read_bytes()
    encoded=base64.b64encode(source).decode()
    program="import base64; exec(compile(base64.b64decode('"+encoded+"'), '<candidate-check>', 'exec'))"
    command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
    result=subprocess.run(ssh_argv(remote)+[command],input=json.dumps(dict(request,workspace=remote['workspace'])),capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('Candidate check failed: '+result.stderr[-2000:])
    return json.loads(result.stdout)
