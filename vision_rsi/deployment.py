"""Standalone, content-addressed remote Training bundle deployment protocol."""
import base64
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile


def sha(value): return hashlib.sha256(value).hexdigest()
def digest(value): return sha(json.dumps(value,sort_keys=True).encode())


def deploy(request):
    root=PurePosixPath(request['workspace'])
    if not root.is_absolute() or '..' in root.parts or str(root)=='/': raise ValueError('Dedicated absolute workspace required')
    files=request.get('files')
    if request.get('parent_directory'):
        if files:raise ValueError('Cannot mix frozen parent sources with local source transfer')
        workspace_root=Path(root).resolve();parent=Path(request['parent_directory']).resolve();releases=(workspace_root/'releases').resolve()
        if not releases.is_relative_to(workspace_root):raise ValueError('Release storage outside workspace')
        if not parent.is_relative_to(releases) or parent==releases:raise ValueError('Frozen parent outside releases')
        manifest=json.loads((parent/'manifest.json').read_text())
        expected=request['parent_sources']
        if manifest['identity']['sources']!=expected:raise ValueError('Frozen parent source identity differs')
        files={}
        for name,checksum in expected.items():
            if not re.fullmatch(r'vision_rsi/[A-Za-z_][A-Za-z0-9_]*\.py',name):raise ValueError('Invalid frozen source name')
            path=(parent/name).resolve()
            if not path.is_relative_to(parent):raise ValueError('Frozen source outside parent')
            content=path.read_bytes()
            if sha(content)!=checksum:raise ValueError('Frozen parent source changed')
            files[name]=base64.b64encode(content).decode()
    if not isinstance(files,dict) or not 1<=len(files)<=100: raise ValueError('Invalid source bundle')
    decoded={}
    for name,value in files.items():
        if not re.fullmatch(r'vision_rsi/[A-Za-z_][A-Za-z0-9_]*\.py',name): raise ValueError('Invalid bundle filename')
        content=base64.b64decode(value,validate=True)
        if len(content)>2*1024*1024: raise ValueError('Oversized source file')
        decoded[name]=content
    if 'vision_rsi/coco_train.py' not in decoded: raise ValueError('Training entry missing')
    identity={'sources':{name:sha(value) for name,value in decoded.items()},'recipe':request['recipe'],'contract':request['contract']}
    bundle_id=digest(identity)
    if request['bundle_id']!=bundle_id: raise ValueError('Bundle identity mismatch')
    workspace=Path(root);releases=workspace/'releases';releases.mkdir(parents=True,exist_ok=True)
    target=releases/bundle_id
    runtime=workspace/'runtime-coco-2.0.11'
    bootstrap='import sys,runpy,json,hashlib\nfrom pathlib import Path\nROOT=Path(__file__).resolve().parent\nmanifest=json.loads((ROOT/"manifest.json").read_text())\nfor name,expected in manifest["artifacts"].items():\n    path=(ROOT/name).resolve()\n    if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:\n        raise RuntimeError("Training bundle artifact integrity failure")\nsys.path[:0]=[str(ROOT),RUNTIME_PLACEHOLDER]\nrunpy.run_module("vision_rsi.coco_train",run_name="__main__")\n'.replace('RUNTIME_PLACEHOLDER',repr(str(runtime)))
    decoded['train.py']=bootstrap.encode()
    decoded['recipe.json']=(json.dumps(request['recipe'],sort_keys=True)+'\n').encode()
    decoded['contract.json']=(json.dumps(request['contract'],sort_keys=True)+'\n').encode()
    manifest={'bundle_id':bundle_id,'identity':identity,'artifacts':{name:sha(value) for name,value in decoded.items()}}
    def verify():
        if json.loads((target/'manifest.json').read_text())!=manifest: raise ValueError('Existing bundle manifest changed')
        for name,expected in manifest['artifacts'].items():
            if sha((target/name).read_bytes())!=expected: raise ValueError('Existing bundle artifact changed')
    if target.exists(): verify()
    else:
        staging=Path(tempfile.mkdtemp(prefix='.deploy-',dir=releases))
        for name,content in decoded.items():
            destination=staging/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2))
        try: staging.rename(target)
        except FileExistsError: verify()  # Preserve staging for audit; never overwrite.
    # Optional dependency can be isolated under the dedicated project workspace.
    sys.path.insert(0,str(runtime))
    try: version=importlib.metadata.version('pycocotools')
    except importlib.metadata.PackageNotFoundError: version=None
    return {'bundle_id':bundle_id,'directory':str(target),'entry':str(target/'train.py'),
            'recipe':str(target/'recipe.json'),'resume_protocol':2 if b'--checkpoint-sha256' in decoded['vision_rsi/coco_train.py'] else 1,'dependencies_ready':version=='2.0.11','pycocotools_version':version}


if __name__=='__main__': print(json.dumps(deploy(json.load(sys.stdin))))
