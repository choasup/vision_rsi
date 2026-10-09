"""Resumable inference batches pinned to one validated capability version."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .runner import atomic_json


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
                identity=value['sample_id']; input_path=value['input']
                if not isinstance(identity,str) or not identity or len(identity)>200: raise ValueError('Invalid sample_id')
                if not isinstance(input_path,str) or not input_path: raise ValueError('input file path required')
                rows.append({'sample_id':identity,'input':str((path.parent/input_path).resolve())})
            except (ValueError,KeyError,TypeError) as error:
                rows.append({'sample_id':f'line-error-{index}','invalid':str(error),'source':line})
    else:
        folder=Path(input_dir).resolve()
        if not folder.is_dir(): raise ValueError('Input directory does not exist')
        rows=[{'sample_id':p.name,'input':str(p.resolve())} for p in sorted(folder.glob('*.json')) if p.is_file()]
    if not rows: raise ValueError('No batch samples')
    if len({r['sample_id'] for r in rows})!=len(rows): raise ValueError('Duplicate sample_id; refusing ambiguous batch')
    return rows


def batch(registry, task_id, rows, output_dir, version=None, resume=False):
    version=registry.resolve_version(task_id,version)
    folder=Path(output_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
    lock=folder/'batch.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        identity={'task_id':task_id,'version':version,'rows':rows}
        path=folder/'batch-state.json'
        if path.exists():
            if not resume: raise ValueError('Batch exists; use --resume or a new output directory')
            state=json.loads(path.read_text(encoding='utf-8'))
            if state['identity']!=identity: raise ValueError('Batch input list or capability version changed')
        else: state={'identity':identity,'items':{}}
        for row in rows:
            key=row['sample_id']; error=None
            try: content_hash=digest_bytes(Path(row['input']).read_bytes()) if 'input' in row else digest_bytes(row['source'].encode())
            except OSError as exc: content_hash=None;error=str(exc)
            old=state['items'].get(key)
            if old and old['input_sha256']!=content_hash: raise ValueError('Sample content changed: '+key)
            output_path=folder/(digest_bytes(key.encode())[:32]+'.json')
            if old and old['status']=='succeeded':
                if not output_path.exists() or digest_bytes(output_path.read_bytes())!=old['output_sha256']:
                    raise ValueError('Saved output missing or changed: '+key)
                continue
            result={'sample_id':key,'task_id':task_id,'capability_version':version,'status':'failed','output':None,'artifacts':[],'error':None}
            try:
                if 'invalid' in row: raise ValueError(row['invalid'])
                if error: raise OSError(error)
                output=registry.infer(task_id,row['input'],version)
                result.update(status='succeeded',output=output['output'],acceptance=output['acceptance'])
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,subprocess.SubprocessError) as exc:
                result['error']={'type':type(exc).__name__,'message':str(exc)[:2000]}
            atomic_json(output_path,result)
            state['items'][key]={'status':result['status'],'input_sha256':content_hash,'output_file':output_path.name,'output_sha256':digest_bytes(output_path.read_bytes())}
            atomic_json(path,state)
        summary={'task_id':task_id,'capability_version':version,'total':len(rows),'succeeded':sum(v['status']=='succeeded' for v in state['items'].values()),'failed':sum(v['status']=='failed' for v in state['items'].values()),'output_dir':str(folder)}
        atomic_json(folder/'summary.json',summary)
        return summary
    finally: lock.unlink()
