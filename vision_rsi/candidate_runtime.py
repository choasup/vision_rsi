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
import signal
import subprocess
import tempfile
import platform
import shutil
import sys


RUNNER='''import importlib,json,sys
sys.path.insert(0,"/work")
request=json.load(sys.stdin)
function=getattr(importlib.import_module(request["module"]),request["function"])
results=[function(**case) for case in request["cases"]]
print(json.dumps({"results":results},allow_nan=False))
'''


def limits():
    import resource
    for key,value in ((resource.RLIMIT_CPU,5),(resource.RLIMIT_AS,512*1024*1024),
                      (resource.RLIMIT_FSIZE,1024*1024),(resource.RLIMIT_NOFILE,32),(resource.RLIMIT_NPROC,32)):
        resource.setrlimit(key,(value,value))


MAX_CASE_BYTES=1024*1024


def runtime_identity():
    """Selected host components only; not the entire mounted dependency tree."""
    def checksum(path):
        path=Path(path);size=path.stat().st_size
        if not path.is_file() or not 0<size<=32*1024*1024:raise ValueError('Runtime binary outside bounded identity scan')
        value=hashlib.sha256();count=0
        with path.open('rb') as stream:
            while block:=stream.read(1024*1024):
                count+=len(block)
                if count>32*1024*1024:raise ValueError('Runtime binary changed or exceeds identity bound')
                value.update(block)
        if count!=size:raise ValueError('Runtime binary changed during identity scan')
        return value.hexdigest()
    bwrap=shutil.which('bwrap')
    if not bwrap:raise ValueError('bwrap missing')
    value={'protocol':'vision-rsi/selected-cpu-runtime/v1','python_binary_sha256':checksum('/usr/bin/python3.12'),
           'bwrap_binary_sha256':checksum(bwrap),'bwrap_path':str(Path(bwrap).resolve()),
           'kernel_release':platform.release(),'machine':platform.machine(),'controller_python':sys.version}
    checksum_value=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    validate_runtime_identity(value,checksum_value)
    return value,checksum_value


def validate_runtime_identity(value,checksum):
    keys={'protocol','python_binary_sha256','bwrap_binary_sha256','bwrap_path','kernel_release','machine','controller_python'}
    if not isinstance(value,dict) or set(value)!=keys or value.get('protocol')!='vision-rsi/selected-cpu-runtime/v1':
        raise ValueError('Invalid selected runtime identity')
    for name in ('python_binary_sha256','bwrap_binary_sha256'):
        if not isinstance(value[name],str) or not re.fullmatch('[0-9a-f]{64}',value[name]):raise ValueError('Invalid runtime binary hash')
    if any(not isinstance(value[name],str) or not 1<=len(value[name])<=512 for name in ('bwrap_path','kernel_release','machine','controller_python')):
        raise ValueError('Invalid runtime identity metadata')
    if not PurePosixPath(value['bwrap_path']).is_absolute() or checksum!=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest():
        raise ValueError('Runtime identity hash or path differs')
    return True


def encode_cases(module,function,cases):
    """Shared local/remote admission; bound the entire serialized request."""
    if not isinstance(module,str) or not re.fullmatch(r'vision_rsi\.(?:strategy|harness|adapter)_[a-z][a-z0-9_]*',module):raise ValueError('Invalid candidate module')
    if not isinstance(function,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',function):raise ValueError('Invalid candidate function')
    if not isinstance(cases,list) or not 1<=len(cases)<=16 or any(not isinstance(case,dict) for case in cases):raise ValueError('Need 1..16 keyword argument cases')
    try:payload=json.dumps({'module':module,'function':function,'cases':cases},allow_nan=False).encode()
    except (ValueError,TypeError) as error:raise ValueError('Candidate cases must be finite JSON data') from error
    if len(payload)>MAX_CASE_BYTES:raise ValueError('Candidate cases too large')
    return payload


def run(request):
    workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/':raise ValueError('Dedicated workspace required')
    environment,environment_hash=runtime_identity()
    expected=request.get('expected_runtime_identity_sha256')
    if expected is not None and expected!=environment_hash:raise ValueError('Selected runtime identity changed; candidate was not executed')
    files=request['files']
    if not isinstance(files,dict) or not 1<=len(files)<=20:raise ValueError('Invalid candidate file set')
    module=request['module'];function=request['function'];cases=request['cases']
    payload=encode_cases(module,function,cases)
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
        command=[environment['bwrap_path'],'--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
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
            if runtime_identity()!=(environment,environment_hash):raise ValueError('Selected runtime changed during execution')
            return {'status':'executed_unverified','observation':value,'source_hashes':hashes,'adopted':False,
                    'runtime_identity':environment,'runtime_identity_sha256':environment_hash,
                    'limits':{'cpu_seconds_per_process':5,'wall_seconds':12,'address_space_bytes_per_process':512*1024*1024,'processes':32,'network':False,'gpu':False},
                    'limitation':'Candidate output is untrusted; not independent quality or RSI adoption evidence.'}


if __name__=='__main__':
    import sys
    print(json.dumps(run(json.load(sys.stdin)),allow_nan=False))
