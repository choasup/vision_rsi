"""One bounded, durable CPU-only resource preparation step per invocation."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import uuid

from .campaign import lease
from .remote import job_request
from .runner import atomic_json, digest


def step(remote, root, directory, request=job_request):
    if not PurePosixPath(root).is_absolute() or '..' in PurePosixPath(root).parts or root == '/':
        raise ValueError('Dedicated absolute remote resource root required')
    remote = {k: v for k, v in remote.items() if k in ('ssh_host','ssh_port','workspace','python')}
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('resource_bootstrap.py').read_bytes()
    sha = hashlib.sha256(source).hexdigest()
    identity = {'remote':remote, 'root':root, 'source_sha256':sha}
    path = directory / 'resources.json'
    with lease(directory / 'resources.lock'):
        state = json.loads(path.read_text()) if path.exists() else {'identity':identity, 'attempts':[]}
        if state['identity'] != identity:
            raise ValueError('Frozen resource source/configuration changed; use a new record directory')
        if state['attempts']:
            attempt = state['attempts'][-1]
            status = request(remote, 'status', attempt['job_id'])
            if status.get('spec_hash') != digest(attempt['spec']):
                raise ValueError('Remote resource job specification mismatch')
            attempt['observation'] = status
            atomic_json(path, state)
            if status['status'] != 'completed':
                return {'job_id':attempt['job_id'], 'status':status['status'],
                        'new_attempt_started':False, 'training_started':False}
            if status.get('gpu_count') != 0 or status.get('gpu_hours') != 0:
                raise ValueError('Resource job unexpectedly used GPU allocation')
            logs = request(remote, 'logs', attempt['job_id'])
            summary = json.loads(logs['log'])
            if summary.get('training_started') is not False or summary.get('gpu_used') is not False:
                raise ValueError('Invalid resource summary')
            from .resource_bootstrap import RESOURCES
            results = summary.get('resources', [])
            if len(results) > len(RESOURCES) or any(r.get('asset') != a for r,a in zip(results,RESOURCES)):
                raise ValueError('Resource summary source mismatch')
            if summary.get('status') == 'downloads_verified':
                if len(results) != len(RESOURCES) or any(r.get('status') != 'downloaded' or
                       r.get('downloaded_bytes') != a['bytes'] or
                       not isinstance(r.get('sha256'),str) or len(r['sha256']) != 64 or
                       any(c not in '0123456789abcdef' for c in r['sha256']) or
                       not r['sha256'].startswith(a.get('sha256_prefix',''))
                       for r,a in zip(results,RESOURCES)):
                    raise ValueError('Incomplete verified download summary')
                attempt['summary'] = summary; atomic_json(path,state)
                return {'status':'downloads_verified','job_id':attempt['job_id'],
                        'dataset_ready':False,'training_started':False}
            if summary.get('status') != 'partial':
                raise ValueError('Unexpected resource summary status')
            attempt['summary'] = summary
        encoded = base64.b64encode(source).decode()
        program = "import base64,hashlib; s=base64.b64decode("+repr(encoded)+"); assert hashlib.sha256(s).hexdigest()=="+repr(sha)+"; exec(compile(s,'<resources>','exec'))"
        spec = {'argv':[remote.get('python','python3'),'-c',program,'--root',root,'--seconds','240'],
                'timeout_seconds':270,'gpu_devices':[],'gpu_hours_budget':0}
        attempt = {'job_id':'resources-'+uuid.uuid4().hex,'spec':spec,'submission':'pending'}
        state['attempts'].append(attempt)
        # An uncertain submit is never retried automatically; next invocation observes this ID.
        atomic_json(path,state)
        response = request(remote,'submit',attempt['job_id'],spec)
        if response.get('spec_hash') != digest(spec):
            raise ValueError('Submission specification mismatch')
        attempt['submission']='acknowledged'; atomic_json(path,state)
        return {'status':'submitted','job_id':attempt['job_id'],'training_started':False,'gpu_count':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--root',required=True)
    parser.add_argument('--records',required=True)
    args=parser.parse_args(argv)
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    print(json.dumps(step(config['remote'],args.root,args.records),indent=2))
