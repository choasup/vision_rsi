"""Resumable inference batches pinned to one validated capability version."""
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .runner import atomic_json
from .campaign import lease

LOCK_MARKER=b'vision-rsi-batch-os-lease-v1\n'


def digest_bytes(value): return hashlib.sha256(value).hexdigest()


def input_rows(manifest=None, input_dir=None):
    if bool(manifest)==bool(input_dir): raise ValueError('Choose one manifest or input directory')
    rows=[]
    if manifest:
        path=Path(manifest).resolve()
        for index,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip(): continue
            try:
                value=json.loads(line)
                if not isinstance(value,dict): raise ValueError('Sample must be an object')
                identity=value['sample_id']
                if not isinstance(identity,str) or not identity or len(identity)>200: raise ValueError('Invalid sample_id')
                if 'inputs' in value:
                    if 'input' in value:raise ValueError('Choose canonical inputs or legacy input path, not both')
                    if not isinstance(value['inputs'],dict) or not value['inputs']:raise ValueError('Named inputs object required')
                    rows.append({'sample_id':identity,'sample':value,'media_base':str(path.parent)})
                else:
                    input_path=value['input']
                    if not isinstance(input_path,str) or not input_path: raise ValueError('input file path required')
                    rows.append({'sample_id':identity,'input':str((path.parent/input_path).resolve())})
            except (ValueError,KeyError,TypeError) as error:
                rows.append({'sample_id':f'line-error-{index}','invalid':str(error),'source':line})
    else:
        folder=Path(input_dir).resolve()
        if not folder.is_dir(): raise ValueError('Input directory does not exist')
        extensions={'.json','.jpg','.jpeg','.png','.bmp','.webp','.tif','.tiff','.gif'}
        rows=[{'sample_id':p.name,'input':str(p.resolve())} for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in extensions]
    if not rows: raise ValueError('No batch samples')
    if len({r['sample_id'] for r in rows})!=len(rows): raise ValueError('Duplicate sample_id; refusing ambiguous batch')
    return rows


def sample_file(row,folder):
    """Freeze an inline contract sample without writing into the input directory."""
    sample=json.loads(json.dumps(row['sample'],allow_nan=False))
    if sample['sample_id']!=row['sample_id']:raise ValueError('Inline sample ID differs from batch row')
    base=Path(row['media_base']).resolve()
    for value in sample['inputs'].values():
        if not isinstance(value,dict):raise ValueError('Named input must be an object')
        kind=value.get('type')
        if kind=='text':continue
        if kind not in ('image','image_list','video'):raise ValueError('Unsupported named input type')
        items=value.get('items') if kind=='image_list' else [value]
        if not isinstance(items,list) or not items:raise ValueError('Image list items required')
        for item in items:
            if not isinstance(item,dict) or not isinstance(item.get('uri'),str) or not item['uri']:raise ValueError('Local media URI required')
            uri=item['uri']
            if uri.startswith('file:'):
                parts=urlsplit(uri)
                if parts.netloc not in ('','localhost') or parts.query or parts.fragment:raise ValueError('Only local file URIs supported')
                local=Path(url2pathname(parts.path))
            else:
                if '://' in uri:raise ValueError('Only local media supported')
                local=Path(uri)
            item['uri']=str((local if local.is_absolute() else base/local).resolve())
    raw=(json.dumps(sample,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>1024*1024:raise ValueError('Inline sample exceeds 1 MiB')
    target=folder/'input-samples'/(digest_bytes(row['sample_id'].encode())[:32]+'.json')
    if not target.parent.resolve().is_relative_to(folder.resolve()):raise ValueError('Inline sample directory escapes batch output')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.is_symlink():raise ValueError('Frozen inline sample changed')
        with target.open('rb') as stream:saved=stream.read(len(raw)+1)
        if saved!=raw:raise ValueError('Frozen inline sample changed')
    else:
        temporary=target.with_suffix('.tmp');temporary.write_bytes(raw);temporary.replace(target)
    return str(target)


def batch(registry, task_id, rows, output_dir, version=None, resume=False):
    version=registry.resolve_version(task_id,version)
    folder=Path(output_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
    lock=folder/'batch.lock'
    try:
        with lock.open('xb') as file:file.write(LOCK_MARKER)
    except FileExistsError:
        try:
            with lock.open('rb') as file:marker=file.read(len(LOCK_MARKER)+1)
        except PermissionError:
            raise RuntimeError('Batch inference is already active or lock is unreadable') from None
        if marker!=LOCK_MARKER:
            raise RuntimeError('Legacy or invalid batch.lock; verify the previous process has stopped before removing it')
    with lease(lock,owner='Batch inference'):
        identity={'task_id':task_id,'version':version,'rows':rows}
        path=folder/'batch-state.json'
        if path.exists():
            if not resume: raise ValueError('Batch exists; use --resume or a new output directory')
            state=json.loads(path.read_text(encoding='utf-8'))
            if state['identity']!=identity: raise ValueError('Batch input list or capability version changed')
        else: state={'identity':identity,'items':{}}
        # Validate the entire saved batch before any new inference is dispatched.
        fingerprints={};prepared_inputs={}
        for row in rows:
            key=row['sample_id']; error=None
            try:
                input_path=sample_file(row,folder) if 'sample' in row else row.get('input')
                prepared_inputs[key]=input_path
                content_hash=(registry.input_fingerprint(task_id,input_path,version) if hasattr(registry,'input_fingerprint') else digest_bytes(Path(input_path).read_bytes())) if input_path is not None else digest_bytes(row['source'].encode())
            except (OSError,ValueError,KeyError,TypeError) as exc: content_hash=None;error=str(exc)
            old=state['items'].get(key)
            if old and old['input_sha256']!=content_hash: raise ValueError('Sample content changed: '+key)
            output_path=folder/(digest_bytes(key.encode())[:32]+'.json')
            if old and old['status']=='succeeded':
                if not output_path.exists() or digest_bytes(output_path.read_bytes())!=old['output_sha256']:
                    raise ValueError('Saved output missing or changed: '+key)
            fingerprints[key]=(content_hash,error)
        for row in rows:
            key=row['sample_id'];content_hash,error=fingerprints[key]
            old=state['items'].get(key)
            if old and old['status']=='succeeded':continue
            output_path=folder/(digest_bytes(key.encode())[:32]+'.json')
            result={'sample_id':key,'task_id':task_id,'capability_version':version,'status':'failed','output':None,'artifacts':[],'error':None}
            try:
                if 'invalid' in row: raise ValueError(row['invalid'])
                if error: raise OSError(error)
                output=registry.infer(task_id,prepared_inputs[key],version,expected_input_fingerprint=content_hash,sample_id=key) if hasattr(registry,'input_fingerprint') else registry.infer(task_id,prepared_inputs[key],version)
                result.update(status='succeeded',output=output['output'],acceptance=output['acceptance'])
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,subprocess.SubprocessError) as exc:
                result['error']={'type':type(exc).__name__,'message':str(exc)[:2000]}
            atomic_json(output_path,result)
            state['items'][key]={'status':result['status'],'input_sha256':content_hash,'output_file':output_path.name,'output_sha256':digest_bytes(output_path.read_bytes())}
            atomic_json(path,state)
        summary={'task_id':task_id,'capability_version':version,'total':len(rows),'succeeded':sum(v['status']=='succeeded' for v in state['items'].values()),'failed':sum(v['status']=='failed' for v in state['items'].values()),'output_dir':str(folder)}
        atomic_json(folder/'summary.json',summary)
        return summary
