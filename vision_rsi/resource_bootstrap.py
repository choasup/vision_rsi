"""Pinned public baseline downloads; no training, extraction or GPU execution."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen


RESOURCES=(
    {'name':'fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth','url':'https://download.pytorch.org/models/fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth',
     'bytes':175221657,'etag':'"9c79e745e559edda1c929951d76934a7-11"','sha256_prefix':'dd69338a'},
    {'name':'annotations_trainval2017.zip','url':'https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip',
     'bytes':252907541,'etag':'"f4bbac642086de4f52a3fdda2de5fa2c"'},
    {'name':'val2017.zip','url':'https://s3.amazonaws.com/images.cocodataset.org/zips/val2017.zip',
     'bytes':815585330,'etag':'"d366be60d3dc737327160d62453e3973-98"'},
)


def save(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');temporary.replace(path)


def checksum(path,deadline):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            if time.monotonic()>=deadline:raise TimeoutError('Download verification deadline reached')
            block=stream.read(1024*1024)
            if not block:break
            value.update(block)
    return value.hexdigest()


def download(asset,root,deadline,opener=urlopen):
    """Resume only the same ETag/size; never append a full response to a part."""
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    name=asset['name']
    if Path(name).name!=name or name in ('','.','..'):raise ValueError('Invalid resource filename')
    final=root/name;part=root/(name+'.part');receipt=root/(name+'.receipt.json')
    for path in (final,part,receipt):
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Resource path escapes download directory')
    if receipt.exists():
        state=json.loads(receipt.read_text(encoding='utf-8'))
        if state.get('asset')!=asset:raise ValueError('Resource source identity changed; no implicit replacement')
    else:
        if final.exists() or part.exists():raise ValueError('Untracked resource retained; refusing overwrite')
        state={'asset':asset,'status':'partial','downloaded_bytes':0};save(receipt,state)
    if final.exists():
        if final.stat().st_size!=asset['bytes'] or checksum(final,deadline)!=state.get('sha256'):raise ValueError('Completed resource changed')
        return dict(state,path=str(final),reused=True)
    offset=part.stat().st_size if part.exists() else 0
    if offset>asset['bytes']:raise ValueError('Partial resource exceeds pinned size')
    if offset<asset['bytes'] and time.monotonic()<deadline:
        headers={'If-Match':asset['etag']}
        if offset:headers['Range']=f'bytes={offset}-'
        request=Request(asset['url'],headers=headers)
        with opener(request,timeout=max(.1,min(15,deadline-time.monotonic()))) as response:
            if response.geturl()!=asset['url'] or response.headers.get('ETag')!=asset['etag']:raise ValueError('Resource URL or ETag differs')
            if offset:
                expected=f"bytes {offset}-{asset['bytes']-1}/{asset['bytes']}"
                if response.status!=206 or response.headers.get('Content-Range')!=expected:raise ValueError('Server did not honor pinned resume range')
            elif response.status!=200:raise ValueError('Unexpected resource HTTP status')
            if int(response.headers.get('Content-Length','-1'))!=asset['bytes']-offset:raise ValueError('Resource response size differs')
            last_saved=offset
            with part.open('ab') as stream:
                while offset<asset['bytes'] and time.monotonic()<deadline:
                    block=response.read1(min(1024*1024,asset['bytes']-offset))
                    if not block:raise ValueError('Resource response ended before pinned size')
                    stream.write(block);offset+=len(block)
                    if offset-last_saved>=8*1024*1024:
                        stream.flush();state.update(status='partial',downloaded_bytes=offset);save(receipt,state);last_saved=offset
    state.update(status='partial',downloaded_bytes=offset);save(receipt,state)
    if offset==asset['bytes'] and time.monotonic()<deadline:
        sha=checksum(part,deadline)
        if state.get('sha256') and sha!=state['sha256']:raise ValueError('Previously verified partial resource changed')
        if not sha.startswith(asset.get('sha256_prefix','')):raise ValueError('Official model SHA-256 prefix mismatch')
        # Persist the verified digest first so a crash across rename is recoverable.
        state.update(status='downloaded',sha256=sha);save(receipt,state)
        if final.exists():raise ValueError('Resource destination appeared; no overwrite')
        part.rename(final)
        return dict(state,path=str(final),reused=False)
    return dict(state,path=str(part))


def run(root,seconds):
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 1<=seconds<=240:raise ValueError('Download step must be 1..240 seconds')
    root=Path(root)
    if not root.is_absolute() or root==Path(root.anchor):raise ValueError('Dedicated absolute resource directory required')
    root.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (root/'bootstrap.lock').open('a+b') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Resource bootstrap already active') from None
        deadline=time.monotonic()+seconds;results=[];error=None
        for asset in RESOURCES:
            try:result=download(asset,root/'downloads',deadline)
            except TimeoutError as failure:error=str(failure);break
            results.append(result)
            save(root/'bootstrap-status.json',{'status':'downloading','resources':results,'training_started':False,'gpu_used':False})
            if result['status']!='downloaded':break
        complete=len(results)==len(RESOURCES) and all(r['status']=='downloaded' for r in results)
        summary={'status':'downloads_verified' if complete else 'partial','resources':results,'error':error,
                 'training_started':False,'gpu_used':False,'dataset_extracted':False,
                 'integrity':'HTTPS pinned URL/ETag/size, model official SHA prefix, computed full SHA; archive CRC/coverage verification pending extraction.'}
        save(root/'bootstrap-status.json',summary);return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--seconds',type=float,default=240)
    args=parser.parse_args();print(json.dumps(run(args.root,args.seconds)))
