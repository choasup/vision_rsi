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
import time


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
    protocol=value.get('protocol') if isinstance(value,dict) else None
    if protocol=='vision-rsi/frozen-cpu-runtime/v2':keys|={'userspace_sha256','userspace_files','userspace_bytes'}
    if not isinstance(value,dict) or set(value)!=keys or protocol not in ('vision-rsi/selected-cpu-runtime/v1','vision-rsi/frozen-cpu-runtime/v2'):
        raise ValueError('Invalid selected runtime identity')
    for name in ('python_binary_sha256','bwrap_binary_sha256'):
        if not isinstance(value[name],str) or not re.fullmatch('[0-9a-f]{64}',value[name]):raise ValueError('Invalid runtime binary hash')
    if any(not isinstance(value[name],str) or not 1<=len(value[name])<=512 for name in ('bwrap_path','kernel_release','machine','controller_python')):
        raise ValueError('Invalid runtime identity metadata')
    if not PurePosixPath(value['bwrap_path']).is_absolute() or checksum!=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest():
        raise ValueError('Runtime identity hash or path differs')
    if protocol.endswith('/v2'):
        if not isinstance(value['userspace_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['userspace_sha256']):raise ValueError('Invalid userspace identity')
        if type(value['userspace_files']) is not int or not 1<=value['userspace_files']<=4096 or type(value['userspace_bytes']) is not int or not 0<value['userspace_bytes']<=256*1024*1024:
            raise ValueError('Userspace identity exceeds bounds')
    return True


def _file_identity(path):
    size=path.stat().st_size
    if not path.is_file() or size>64*1024*1024:raise ValueError('Runtime file exceeds 64 MiB')
    value=hashlib.sha256();count=0
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):
            count+=len(block)
            if count>64*1024*1024:raise ValueError('Runtime file grew beyond bound')
            value.update(block)
    if count!=size:raise ValueError('Runtime file changed during capture')
    return {'kind':'file','bytes':count,'sha256':value.hexdigest()}


def _ldd_paths(text):
    if 'not found' in text:raise ValueError('Missing native runtime dependency')
    paths=[]
    for line in text.splitlines():
        match=re.search(r'=>\s+(/\S+)',line) or re.match(r'\s*(/\S+)',line)
        if match:paths.append(Path(match.group(1)))
        elif line.strip() and not ('linux-vdso' in line or 'statically linked' in line):raise ValueError('Unrecognized dependency inspection output')
    return paths


def _elf_executable(path):
    with path.open('rb') as stream:header=stream.read(20)
    if len(header)<18 or header[:4]!=b'\x7fELF' or header[5] not in (1,2):return False
    kind=int.from_bytes(header[16:18],'little' if header[5]==1 else 'big')
    return kind in (2,3)


def userspace_spec():
    """Capture only /usr Python runtime files and their resolved ELF dependencies."""
    entries={};sources={};queue=[];total=0;deadline=time.monotonic()+12
    def admit(path):
        nonlocal total
        if time.monotonic()>deadline:raise ValueError('Runtime capture inspection deadline exceeded')
        name=str(path)
        if name in entries:return
        if not (name=='/usr/bin/python3.12' or name.startswith('/usr/lib/')) or '..' in PurePosixPath(name).parts:
            raise ValueError('Native dependency outside supported userspace roots')
        if path.is_symlink():
            entries[name]={'kind':'symlink','target':os.readlink(path)}
            target=Path(os.path.normpath(os.path.join(str(path.parent),os.readlink(path))))
            resolved=path.resolve()
            # Capture each alias in the chain, not only its final inode.
            if target.is_file() and str(target).startswith('/usr/lib/'):admit(target)
            elif resolved.is_dir() and not resolved.is_relative_to(Path('/usr/lib/python3.12')):
                raise ValueError('Unsupported external standard-library directory alias')
        elif path.is_file():
            row=_file_identity(path);entries[name]=row;sources[name]=path;total+=row['bytes']
            if _elf_executable(path):queue.append(path)
        else:raise ValueError('Unsupported runtime filesystem entry')
        if len(entries)>4096 or total>256*1024*1024:raise ValueError('Runtime capture exceeds file/byte bounds')
    admit(Path('/usr/bin/python3.12'))
    for path in Path('/usr/lib/python3.12').rglob('*'):
        if time.monotonic()>deadline:raise ValueError('Runtime capture inspection deadline exceeded')
        if path.is_symlink() or not path.is_dir():admit(path)
    inspected=set()
    while queue:
        path=queue.pop()
        if path in inspected:continue
        inspected.add(path);remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('Runtime dependency inspection deadline exceeded')
        result=subprocess.run(['/usr/bin/ldd',str(path)],capture_output=True,text=True,timeout=min(2,remaining),env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
        if result.returncode:raise ValueError('Native dependency inspection failed for '+str(path)+': '+(result.stdout+result.stderr)[:300])
        for dependency in _ldd_paths(result.stdout):
            name=str(dependency)
            if name.startswith('/lib/'):dependency=Path('/usr'+name)
            elif name.startswith('/lib64/'):dependency=Path('/usr/lib/x86_64-linux-gnu')/dependency.name
            admit(dependency)
    manifest={'format':'vision-rsi/cpu-userspace/v1','entries':entries,'files':len(entries),'bytes':total}
    return manifest,sources


def verify_userspace(root,manifest):
    expected=manifest['entries'];actual=set();directories=set()
    for path in (root/'usr').rglob('*'):
        name='/'+path.relative_to(root).as_posix()
        if path.is_symlink():row={'kind':'symlink','target':os.readlink(path)}
        elif path.is_dir():directories.add(name);continue
        else:row=_file_identity(path)
        if expected.get(name)!=row:raise ValueError('Frozen userspace content differs')
        actual.add(name)
    wanted_dirs={str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) not in ('/','/usr')}
    if actual!=set(expected) or directories!=wanted_dirs:raise ValueError('Frozen userspace file/directory set differs')


def freeze_userspace(workspace):
    manifest,sources=userspace_spec()
    checksum=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    cache=Path(workspace)/'runtime-snapshots';cache.mkdir(parents=True,exist_ok=True);root=cache/checksum[:32]
    if root.exists():
        with (root/'manifest.json').open() as stream:saved=json.load(stream)
        if saved!=manifest:raise ValueError('Frozen userspace manifest differs')
        verify_userspace(root,manifest);return root,manifest,checksum
    stage=Path(tempfile.mkdtemp(prefix='runtime-',dir=cache))
    try:
        for name,row in manifest['entries'].items():
            target=stage/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
            if row['kind']=='symlink':os.symlink(row['target'],target)
            else:
                shutil.copyfile(sources[name],target);target.chmod(0o555);os.utime(target,(0,0))
        verify_userspace(stage,manifest)
        (stage/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
        try:stage.rename(root)
        except OSError:
            if not root.exists():raise
            with (root/'manifest.json').open() as stream:saved=json.load(stream)
            if saved!=manifest:raise ValueError('Concurrent runtime snapshot differs')
            verify_userspace(root,manifest)
    finally:
        if stage.exists():
            if not stage.resolve().is_relative_to(cache.resolve()):raise ValueError('Unsafe runtime stage cleanup path')
            def writable(function,path,error):
                os.chmod(path,0o700);function(path)
            shutil.rmtree(stage,onerror=writable)
    return root,manifest,checksum


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
    runtime_root,runtime_manifest,userspace_hash=freeze_userspace(str(workspace))
    environment=dict(environment,protocol='vision-rsi/frozen-cpu-runtime/v2',userspace_sha256=userspace_hash,
                     userspace_files=runtime_manifest['files'],userspace_bytes=runtime_manifest['bytes'])
    environment_hash=hashlib.sha256(json.dumps(environment,sort_keys=True).encode()).hexdigest()
    validate_runtime_identity(environment,environment_hash)
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
                 '--ro-bind',str(runtime_root/'usr'),'/usr',
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
            verify_userspace(runtime_root,runtime_manifest)
            after,_=runtime_identity()
            original={k:v for k,v in environment.items() if k not in ('userspace_sha256','userspace_files','userspace_bytes','protocol')}
            original['protocol']='vision-rsi/selected-cpu-runtime/v1'
            if after!=original:
                raise ValueError('Selected runtime changed during execution')
            return {'status':'executed_unverified','observation':value,'source_hashes':hashes,'adopted':False,
                    'runtime_identity':environment,'runtime_identity_sha256':environment_hash,
                    'limits':{'cpu_seconds_per_process':5,'wall_seconds':12,'address_space_bytes_per_process':512*1024*1024,'processes':32,'network':False,'gpu':False},
                    'limitation':'Candidate output is untrusted; not independent quality or RSI adoption evidence.'}


if __name__=='__main__':
    import sys
    print(json.dumps(run(json.load(sys.stdin)),allow_nan=False))
