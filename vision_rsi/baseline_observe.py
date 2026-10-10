"""Observe a pinned CPU baseline job from the local CLI without launching work."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess

from .remote import job_request, ssh_argv
from .runner import digest


PROBE = '''import json,hashlib,sys,base64
from pathlib import Path
request=json.load(sys.stdin)
workspace=Path(request['workspace']).resolve()
context=request['context']
bundle=Path(context['bundle_directory']).resolve()
root=Path(context['dataset_root']).resolve()
output=Path(context['output_directory']).resolve()
if not bundle.is_relative_to(workspace/'releases') or any(not p.is_relative_to(workspace) for p in (root,output)):
 raise ValueError('Observation paths outside dedicated workspace')
manifest=json.loads((bundle/'manifest.json').read_text())
if hashlib.sha256(json.dumps(manifest['identity'],sort_keys=True).encode()).hexdigest()!=context['bundle_id']:
 raise ValueError('Bundle identity mismatch')
for name,sha in manifest['artifacts'].items():
 path=(bundle/name).resolve()
 if not path.is_relative_to(bundle) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Frozen bundle changed')
for name,sha in manifest['identity']['sources'].items():
 if manifest['artifacts'].get(name)!=sha:raise ValueError('Frozen source manifest mismatch')
state=json.loads((output/'state.json').read_text()) if (output/'state.json').exists() else None
if state is not None and state.get('identity')!=context['identity']:raise ValueError('Baseline identity mismatch')
result={'saved_prediction_files':len(list(output.glob('[0-9]*.json'))),'last_completed_step':state,
        'audited':False,'quality_verified':False,'read_only':True}
if request['audit']:
 source=base64.b64decode(request['audit_source'],validate=True)
 if hashlib.sha256(source).hexdigest()!=request['audit_source_sha256']:raise ValueError('Audit source mismatch')
 sys.path.insert(0,str(bundle))
 scope={'__name__':'vision_rsi.audit_observer','__package__':'vision_rsi'}
 exec(compile(source,'<baseline-audit>','exec'),scope)
 result['audit']=scope['audit'](root,output,context['identity'],context['annotation_sha256'])
 result['saved_prediction_files']=result['audit']['audited_images']
 result['audited']=True
print(json.dumps(result))
'''


def observe(record, audit=False):
    context=record.get('observation_context')
    required={'bundle_directory','bundle_id','dataset_root','output_directory','identity','annotation_sha256'}
    if not isinstance(context,dict) or set(context)!=required:
        raise ValueError('Frozen baseline observation context required')
    for key in ('bundle_id','identity','annotation_sha256'):
        value=context[key]
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Invalid observation identity')
    for key in ('bundle_directory','dataset_root','output_directory'):
        value=PurePosixPath(context[key])
        if not value.is_absolute() or '..' in value.parts:raise ValueError('Absolute remote observation path required')
    remote=record['remote'];spec=record['spec']
    if spec.get('gpu_devices')!=[] or spec.get('gpu_hours_budget')!=0:
        raise ValueError('Observer supports CPU baseline jobs only')
    status=job_request(remote,'status',record['job_id'])
    if status.get('spec_hash')!=digest(spec):raise ValueError('Remote job differs from frozen specification')
    source=Path(__file__).with_name('baseline_audit.py').read_bytes()
    sha=hashlib.sha256(source).hexdigest()
    request={'workspace':remote['workspace'],'context':context,'audit':bool(audit),
             'audit_source':base64.b64encode(source).decode(),'audit_source_sha256':sha}
    result=subprocess.run(ssh_argv(remote)+[shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(PROBE)],
                          input=json.dumps(request),capture_output=True,text=True,timeout=45)
    if result.returncode:raise RuntimeError('Read-only baseline observation failed: '+result.stderr[-1500:])
    observed=json.loads(result.stdout)
    if observed.get('read_only') is not True or observed.get('quality_verified') is not False:
        raise ValueError('Invalid baseline observation receipt')
    if audit and (observed.get('audited') is not True or observed['audit']['identity']!=context['identity']
                  or observed['audit']['quality_verified'] is not False):
        raise ValueError('Audit receipt does not match baseline identity')
    return {'job_id':record['job_id'],'worker_status':status['status'],'remote_status_observed':True,
            'audit_source_sha256':sha if audit else None,'observation':observed,
            'training_started':False,'capability_registered':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',required=True,help='Local frozen baseline job record JSON')
    parser.add_argument('--audit',action='store_true')
    args=parser.parse_args(argv)
    print(json.dumps(observe(json.loads(Path(args.job).read_text()),args.audit),indent=2))
