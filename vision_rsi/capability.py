"""Training/inference task contracts and immutable local capability artifacts."""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

from .runner import atomic_json, revision
from .toy_harness import predict, iou


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def task_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',value):
        raise ValueError('task_id must be a safe 1..64 character identifier')
    return value


class Capabilities:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'registry.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS versions(task_id TEXT, version TEXT UNIQUE, status TEXT, manifest_hash TEXT, created INTEGER PRIMARY KEY AUTOINCREMENT)')

    def close(self): self.db.close()

    def list(self):
        return [{'task_id':a,'version':b,'status':c} for a,b,c in self.db.execute('SELECT task_id,version,status FROM versions ORDER BY created')]

    def train(self, spec_path):
        spec_path=Path(spec_path).resolve(); spec=json.loads(spec_path.read_text(encoding='utf-8'))
        name=task_id(spec['task_id'])
        if spec.get('kind') not in ('toy_threshold_detection','coco_detection'):
            raise ValueError('Unsupported task kind')
        version=uuid.uuid4().hex
        folder=self.root/name/version; folder.mkdir(parents=True)
        manifest={'task_id':name,'version':version,'spec':spec,'git_revision':revision(), 'status':'blocked',
                  'limitations':'No RSI self-modification. Toy detection is not COCO or a general object detector.'}
        def finish(status):
            manifest['status']=status
            atomic_json(folder/'manifest.json',manifest)
            with self.db:
                self.db.execute('INSERT INTO versions(task_id,version,status,manifest_hash) VALUES (?,?,?,?)',(name,version,status,sha(folder/'manifest.json')))
            return manifest
        if spec['kind']=='coco_detection':
            manifest['reason']='COCO training adapter, frozen detector/weights, dataset paths and GPU budget are required; no inference capability registered as validated.'
            return finish('blocked')
        try:
            acceptance=spec['acceptance']
            target=acceptance['threshold']
            if acceptance['metric']!='mean_iou' or isinstance(target,bool) or not isinstance(target,(int,float)) or not math.isfinite(target) or not 0<=target<=1:
                raise ValueError('Toy acceptance must be mean_iou threshold in [0,1]')
            candidates=spec['search']['thresholds']; limit=spec['budget']['max_candidates']
            if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=256:
                raise ValueError('max_candidates must be 1..256')
            if not isinstance(candidates,list) or not candidates or len(candidates)>limit or len(set(candidates))!=len(candidates):
                raise ValueError('Candidate set exceeds budget or contains duplicates')
            if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<=x<=255 for x in candidates):
                raise ValueError('Invalid threshold candidate')
            data_path=(spec_path.parent/spec['training_data']).resolve()
            data=json.loads(data_path.read_text(encoding='utf-8'))
            train,validation=data['train'],data['validation']
            if not train or not validation: raise ValueError('Separate nonempty train/validation splits required')
            train_ids={json.dumps(x['image'],sort_keys=True) for x in train}
            if any(json.dumps(x['image'],sort_keys=True) in train_ids for x in validation):
                raise ValueError('Identical images in training and validation splits')
            def score(samples,threshold):
                return sum(iou(predict(s['image'],threshold),s['bbox']) for s in samples)/len(samples)
            trials=[{'threshold':t,'training_mean_iou':score(train,t)} for t in candidates]
            best=max(trials,key=lambda row:row['training_mean_iou'])
            metric=score(validation,best['threshold'])
            manifest.update(trials=trials,validation={'mean_iou':metric,'evaluations':1,'used_for_search':False},data_sha256=sha(data_path),
                            input_schema={'image':'nonempty rectangular 0..255 intensity matrix'},output_schema={'predictions':'bbox xywh, category_id=1, score=1.0 (not calibrated)'},actual_gpu_hours=0)
            atomic_json(folder/'model.json',{'threshold':best['threshold']})
            source=Path(__file__).with_name('toy_harness.py')
            (folder/'harness.py').write_bytes(source.read_bytes())
            manifest['artifacts']={file:sha(folder/file) for file in ('model.json','harness.py')}
            return finish('validated' if metric>=target else 'not_met')
        except (ValueError,KeyError,TypeError,OSError) as error:
            manifest['reason']=type(error).__name__+': '+str(error)
            return finish('failed')

    def infer(self, name, input_path, version=None):
        name=task_id(name)
        if version:
            row=self.db.execute("SELECT version,manifest_hash FROM versions WHERE task_id=? AND version=? AND status='validated'",(name,version)).fetchone()
        else:
            row=self.db.execute("SELECT version,manifest_hash FROM versions WHERE task_id=? AND status='validated' ORDER BY created DESC LIMIT 1",(name,)).fetchone()
        if not row: raise ValueError('No validated capability for task/version; run training and inspect acceptance first')
        version,expected=row; folder=self.root/name/version
        if sha(folder/'manifest.json')!=expected: raise ValueError('Manifest integrity failure')
        manifest=json.loads((folder/'manifest.json').read_text())
        for file,expected_hash in manifest['artifacts'].items():
            if file not in ('model.json','harness.py') or sha(folder/file)!=expected_hash: raise ValueError('Artifact integrity failure')
        output=subprocess.check_output([sys.executable,str(folder/'harness.py'),str(folder/'model.json'),str(Path(input_path).resolve())],text=True,timeout=30)
        return {'task_id':name,'version':version,'kind':manifest['spec']['kind'],'output':json.loads(output),'acceptance':manifest['validation']}
