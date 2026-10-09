"""Read-only remote collection of bounded Training reports and artifact hashes."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


def file_sha(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def collect(request):
    workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/': raise ValueError('Dedicated absolute workspace required')
    run_id=request['run_id']
    if not re.fullmatch(r'train-[a-f0-9]{32}',run_id): raise ValueError('Invalid Training run ID')
    root=(Path(workspace)/'training').resolve()
    folder=Path(request['output_directory']).resolve()
    if folder.name!=run_id or not folder.is_relative_to(root): raise ValueError('Output path outside Training workspace')
    files={};hashes={}
    for name in ('result.json','evaluation.json','progress.json','checkpoint.pt','predictions.json','coverage.json'):
        path=folder/name
        if not path.resolve().is_relative_to(folder) or not path.is_file(): raise ValueError('Missing or escaping artifact: '+name)
        if name in ('result.json','evaluation.json','progress.json'):
            if path.stat().st_size>2*1024*1024: raise ValueError('Oversized report: '+name)
            content=path.read_bytes()
            files[name]={'sha256':hashlib.sha256(content).hexdigest(),'base64':base64.b64encode(content).decode()}
        else: hashes[name]=file_sha(path)
    return {'run_id':run_id,'output_directory':str(folder),'reports':files,'artifact_hashes':hashes}


if __name__=='__main__':print(json.dumps(collect(json.load(sys.stdin))))
