"""Read-only, time-bounded CPU resource gate before any GPU job submission."""
import hashlib
import json
import shlex
import subprocess

from .remote import ssh_argv
from .runner import digest


PROBE = '''import os,signal,json,hashlib,sys
from pathlib import Path
os.environ['CUDA_VISIBLE_DEVICES']=''
signal.alarm(90)
request=json.load(sys.stdin)
workspace=Path(request['workspace']).resolve()
bundle=Path(request['deployment']['directory']).resolve()
if not bundle.is_relative_to(workspace/'releases'):raise ValueError('Training bundle outside releases')
manifest=json.loads((bundle/'manifest.json').read_text())
identity=manifest['identity']
sha=lambda value:hashlib.sha256(value).hexdigest()
if sha(json.dumps(identity,sort_keys=True).encode())!=request['deployment']['bundle_id']:
 raise ValueError('Frozen bundle identity differs')
expected={'vision_rsi/'+name:value for name,value in request['sources'].items()}
if identity['sources']!=expected or identity['recipe']!=request['recipe'] or identity['contract']!=request['contract']:
 raise ValueError('Training plan and deployment differ')
for name,checksum in manifest['artifacts'].items():
 path=(bundle/name).resolve()
 if not path.is_relative_to(bundle) or sha(path.read_bytes())!=checksum:raise ValueError('Frozen bundle changed')
for name,checksum in expected.items():
 if manifest['artifacts'].get(name)!=checksum:raise ValueError('Frozen source manifest differs')
if json.loads((bundle/'recipe.json').read_text())!=request['recipe']:raise ValueError('Frozen recipe changed')
sys.path[:0]=[str(bundle),str(workspace/'runtime-coco-2.0.11')]
from vision_rsi.coco_train import preflight
train,val=preflight(request['recipe'])
print(json.dumps({'status':'resources_verified','bundle_id':request['deployment']['bundle_id'],
 'recipe_sha256':sha(json.dumps(request['recipe'],sort_keys=True).encode()),
 'train_images':len(train),'validation_images':len(val),'gpu_used':False,'training_started':False}))
'''


def check(remote, deployment, plan):
    from .coco_train import validate_recipe
    validate_recipe(plan['recipe'],path_flavor='posix')
    request={'workspace':remote['workspace'],'deployment':deployment,'recipe':plan['recipe'],
             'contract':plan['contract'],'sources':plan['source_hashes']}
    result=subprocess.run(ssh_argv(remote)+[shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(PROBE)],
                          input=json.dumps(request),capture_output=True,text=True,timeout=100)
    if result.returncode:
        raise RuntimeError('CPU Training resource preflight failed: '+result.stderr[-1500:])
    report=json.loads(result.stdout)
    expected=(118287,5000) if not plan['recipe'].get('fixture',False) else None
    counts=(report.get('train_images'),report.get('validation_images'))
    if (report.get('status')!='resources_verified' or report.get('bundle_id')!=deployment['bundle_id']
            or report.get('recipe_sha256')!=digest(plan['recipe']) or report.get('gpu_used') is not False
            or report.get('training_started') is not False or any(type(n) is not int or n<1 for n in counts)
            or (expected is not None and counts!=expected)):
        raise ValueError('CPU resource preflight receipt does not match frozen Training plan')
    return dict(report,validator_sha256=hashlib.sha256(PROBE.encode()).hexdigest())
