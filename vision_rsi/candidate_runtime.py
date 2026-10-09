"""Remote CPU-only, no-network namespace runner for bounded candidate checks.

This driver is owned by the control plane, not candidate code. Its output is
runtime evidence only, never a quality/adoption verdict.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import signal
import subprocess
import tempfile


RUNNER='''import importlib,json,sys
sys.path.insert(0,"/work")
request=json.load(sys.stdin)
function=getattr(importlib.import_module(request["module"]),request["function"])
results=[function(**case) for case in request["cases"]]
print(json.dumps({"results":results},allow_nan=False))
'''


def limits():
    for key,value in ((resource.RLIMIT_CPU,5),(resource.RLIMIT_AS,512*1024*1024),
                      (resource.RLIMIT_FSIZE,1024*1024),(resource.RLIMIT_NOFILE,32),(resource.RLIMIT_NPROC,32)):
        resource.setrlimit(key,(value,value))


def run(request):
    workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/':raise ValueError('Dedicated workspace required')
    files=request['files']
    if not isinstance(files,dict) or not 1<=len(files)<=20:raise ValueError('Invalid candidate file set')
    module=request['module'];function=request['function'];cases=request['cases']
    if not re.fullmatch(r'vision_rsi\.(?:strategy|harness|adapter)_[a-z][a-z0-9_]*',module):raise ValueError('Invalid candidate module')
    if not re.fullmatch('[a-z][a-z0-9_]{0,63}',function):raise ValueError('Invalid candidate function')
    if not isinstance(cases,list) or not 1<=len(cases)<=16 or any(not isinstance(case,dict) for case in cases):raise ValueError('Need 1..16 keyword argument cases')
    payload=json.dumps({'module':module,'function':function,'cases':cases},allow_nan=False).encode()
    if len(payload)>64*1024:raise ValueError('Candidate cases too large')
    root=Path(workspace)/'candidate-checks';root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='check-',dir=root) as temp:
        source=Path(temp);source.chmod(0o755)
        (source/'vision_rsi').mkdir(mode=0o755);(source/'vision_rsi/__init__.py').write_text('')
        hashes={}
        for name,encoded in files.items():
            if not re.fullmatch(r'vision_rsi/(?:research|(?:strategy|harness|adapter)_[a-z][a-z0-9_]*)\.py',name):raise ValueError('Invalid candidate source path')
            raw=base64.b64decode(encoded,validate=True)
            if len(raw)>256*1024:raise ValueError('Candidate source too large')
            target=source/name;target.write_bytes(raw);target.chmod(0o444)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        if hashes!=request['source_hashes']:raise ValueError('Candidate source identity differs')
        runner=source/'runner.py';runner.write_text(RUNNER);runner.chmod(0o444)
        # Mount no host home, /etc, credentials, workspace, GPUs, sockets or proc.
        command=['bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
                 '--uid','65534','--gid','65534','--clearenv','--setenv','LANG','C.UTF-8',
                 '--ro-bind','/usr/bin/python3.12','/usr/bin/python3.12',
                 '--ro-bind','/usr/lib/python3.12','/usr/lib/python3.12',
                 '--ro-bind','/usr/lib/x86_64-linux-gnu','/usr/lib/x86_64-linux-gnu',
                 '--symlink','usr/lib','/lib','--dir','/lib64',
                 '--symlink','/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/lib64/ld-linux-x86-64.so.2',
                 '--ro-bind',str(source),'/work','--dir','/tmp','--chdir','/work',
                 '--remount-ro','/','/usr/bin/python3.12','-I','-B','/work/runner.py']
        with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
            child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=output,stderr=errors,start_new_session=True,preexec_fn=limits)
            try:child.communicate(payload,timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);child.wait()
                return {'status':'timed_out','source_hashes':hashes,'adopted':False}
            output.seek(0);errors.seek(0);raw=output.read(1024*1024+1);error=errors.read(4000).decode(errors='replace')
            if child.returncode:return {'status':'failed','returncode':child.returncode,'error':error,'source_hashes':hashes,'adopted':False}
            if len(raw)>1024*1024:raise ValueError('Candidate output too large')
            value=json.loads(raw)
            if not isinstance(value,dict) or not isinstance(value.get('results'),list) or len(value['results'])!=len(cases):raise ValueError('Candidate runtime response shape differs')
            return {'status':'executed_unverified','observation':value,'source_hashes':hashes,'adopted':False,
                    'limits':{'cpu_seconds_per_process':5,'wall_seconds':12,'address_space_bytes_per_process':512*1024*1024,'processes':32,'network':False,'gpu':False},
                    'limitation':'Candidate output is untrusted; not independent quality or RSI adoption evidence.'}


if __name__=='__main__':
    import sys
    print(json.dumps(run(json.load(sys.stdin)),allow_nan=False))
