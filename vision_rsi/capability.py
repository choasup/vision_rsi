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

    def register_training(self,record,sample_path):
        from .acceptance import review
        from .media import image_request
        from .remote import infer_training
        from .runner import digest
        if not sample_path:raise ValueError('A local contract sample is required to verify the inference adapter')
        if record['status']!='completed': raise ValueError('Training process must be completed before registration')
        details=record['details']
        plan=json.loads(Path(details['plan_path']).read_text(encoding='utf-8'))
        if digest(plan)!=record['plan_id']: raise ValueError('Frozen Training plan changed')
        receipt=json.loads(Path(details['receipt_path']).read_text(encoding='utf-8'))
        if receipt['run_id']!=record['run_id']: raise ValueError('Training receipt belongs to another run')
        verdict=review(plan,receipt)
        if not verdict['passed']: raise ValueError('Training acceptance not met; no capability registered: '+'; '.join(verdict['reasons']))
        import base64
        result=json.loads(base64.b64decode(receipt['reports']['result.json']['base64']))
        name=task_id(plan['task_id']);version=uuid.uuid4().hex
        folder=self.root/name/version;folder.mkdir(parents=True)
        atomic_json(folder/'plan.json',plan);atomic_json(folder/'receipt.json',receipt)
        (folder/'inference.py').write_bytes(Path(__file__).with_name('coco_infer.py').read_bytes())
        endpoint={'remote':record['remote'],'bundle_directory':details['deployment']['directory'],
                  'checkpoint':details['output_directory']+'/checkpoint.pt','checkpoint_sha256':verdict['checkpoint_sha256'],
                  'training_identity_hash':result['identity_hash'],'source_hashes':plan['source_hashes'],'recipe':plan['recipe'],'contract':plan['contract']}
        request=dict(image_request(plan['contract'],sample_path),**{key:value for key,value in endpoint.items() if key!='remote'})
        probe=infer_training(endpoint['remote'],request,folder/'inference.py')
        self._verify_remote_prediction(endpoint,request,probe)
        manifest={'task_id':name,'version':version,'status':'pending_serving_validation','spec':{'kind':'coco_detection'},'training_run_id':record['run_id'],'session_id':record['session_id'],
                  'endpoint':endpoint,'validation':dict(verdict,status='pending_serving_validation',capability_registered=False,serving_backend='cpu',serving_accuracy_verified=False),'registration_sample_sha256':probe['image_sha256'],
                  'limitations':'COCO AP measured by frozen Training evaluation; CPU serving accuracy and latency need deployment validation. Not a guarantee for arbitrary input.',
                  'artifacts':{file:sha(folder/file) for file in ('plan.json','receipt.json','inference.py')}}
        atomic_json(folder/'manifest.json',manifest)
        with self.db:self.db.execute('INSERT INTO versions(task_id,version,status,manifest_hash) VALUES (?,?,?,?)',(name,version,'pending_serving_validation',sha(folder/'manifest.json')))
        return manifest

    def evaluate_serving(self,name,version,wall_seconds_budget,chunk_size=10):
        from .remote import serving_step
        name=task_id(name)
        row=self.db.execute("SELECT manifest_hash FROM versions WHERE task_id=? AND version=? AND status='pending_serving_validation'",(name,version)).fetchone()
        if not row:raise ValueError('No pending serving candidate')
        folder=self.root/name/version
        if sha(folder/'manifest.json')!=row[0]:raise ValueError('Candidate manifest integrity failure')
        manifest=json.loads((folder/'manifest.json').read_text())
        if set(manifest['artifacts'])!={'plan.json','receipt.json','inference.py'}:raise ValueError('Candidate artifact set mismatch')
        for file,expected in manifest['artifacts'].items():
            if sha(folder/file)!=expected:raise ValueError('Candidate artifact integrity failure')
        response=serving_step(manifest['endpoint']['remote'],manifest['endpoint'],folder/'inference.py',wall_seconds_budget,chunk_size)
        if response.get('status')=='evaluated':
            report_path=folder/'serving-evaluation.json'
            atomic_json(report_path,response['report'])
            return self.promote_serving(name,version,report_path)
        if response.get('status') not in ('pending','budget_exhausted'):raise ValueError('Unexpected serving evaluation response')
        return dict(response,task_id=name,version=version)

    def promote_serving(self,name,version,report_path):
        from .serving_acceptance import review_serving
        name=task_id(name)
        row=self.db.execute("SELECT manifest_hash FROM versions WHERE task_id=? AND version=? AND status='pending_serving_validation'",(name,version)).fetchone()
        if not row:raise ValueError('No pending serving candidate')
        folder=self.root/name/version
        if sha(folder/'manifest.json')!=row[0]:raise ValueError('Candidate manifest integrity failure')
        manifest=json.loads((folder/'manifest.json').read_text())
        for file,expected in manifest['artifacts'].items():
            if file not in ('plan.json','receipt.json','inference.py') or sha(folder/file)!=expected:raise ValueError('Candidate artifact integrity failure')
        report_bytes=Path(report_path).read_bytes()
        report=json.loads(report_bytes.decode('utf-8-sig'))
        verdict=review_serving(manifest,report)
        new_version=uuid.uuid4().hex;destination=self.root/name/new_version;destination.mkdir()
        for file in manifest['artifacts']:(destination/file).write_bytes((folder/file).read_bytes())
        (destination/'serving-report.json').write_bytes(report_bytes)
        updated=dict(manifest,version=new_version,parent_version=version,status='validated',validation=verdict,
                     limitations='Serving AP is measured on the frozen COCO validation set; arbitrary-input quality is not guaranteed.')
        updated['artifacts']=dict(manifest['artifacts'],**{'serving-report.json':sha(destination/'serving-report.json')})
        atomic_json(destination/'manifest.json',updated)
        with self.db:self.db.execute('INSERT INTO versions(task_id,version,status,manifest_hash) VALUES (?,?,?,?)',(name,new_version,'validated',sha(destination/'manifest.json')))
        return updated

    @staticmethod
    def _verify_remote_prediction(endpoint,request,response):
        import base64
        from .contracts import validate_schema
        if response.get('sample_id')!=request['sample']['sample_id'] or response.get('checkpoint_sha256')!=endpoint['checkpoint_sha256'] or response.get('training_identity_hash')!=endpoint['training_identity_hash']:
            raise ValueError('Inference response does not match registered sample/model')
        if response.get('image_sha256')!=hashlib.sha256(base64.b64decode(request['image_base64'])).hexdigest():
            raise ValueError('Inference response image bytes differ')
        if response.get('device')!='cpu':raise ValueError('Unexpected inference serving backend')
        validate_schema(endpoint['contract']['output_schema'],response['output'])

    def resolve_version(self, name, version=None):
        name=task_id(name)
        rows=self.db.execute("SELECT version,manifest_hash FROM versions WHERE task_id=? AND status='validated' ORDER BY created DESC",(name,)).fetchall()
        for candidate,expected in rows:
            if version and candidate!=version:continue
            path=self.root/name/candidate/'manifest.json'
            if sha(path)!=expected:raise ValueError('Manifest integrity failure')
            manifest=json.loads(path.read_text())
            if manifest['spec']['kind']=='coco_detection' and manifest.get('validation',{}).get('serving_accuracy_verified') is not True:continue
            return candidate
        raise ValueError('No validated capability for task/version; serving validation may be pending')

    def input_fingerprint(self,name,input_path,version=None):
        name=task_id(name);version=self.resolve_version(name,version)
        expected=self.db.execute("SELECT manifest_hash FROM versions WHERE task_id=? AND version=?",(name,version)).fetchone()[0]
        path=self.root/name/version/'manifest.json'
        if sha(path)!=expected:raise ValueError('Manifest integrity failure')
        manifest=json.loads(path.read_text())
        if manifest['spec']['kind']=='coco_detection':
            from .media import image_request
            return image_request(manifest['endpoint']['contract'],input_path)['input_fingerprint']
        return sha(input_path)

    def infer(self, name, input_path, version=None,expected_input_fingerprint=None,sample_id=None):
        name=task_id(name)
        version=self.resolve_version(name,version)
        row=self.db.execute("SELECT version,manifest_hash FROM versions WHERE task_id=? AND version=? AND status='validated'",(name,version)).fetchone()
        version,expected=row; folder=self.root/name/version
        if sha(folder/'manifest.json')!=expected: raise ValueError('Manifest integrity failure')
        manifest=json.loads((folder/'manifest.json').read_text())
        allowed=('plan.json','receipt.json','inference.py','serving-report.json') if manifest['spec']['kind']=='coco_detection' else ('model.json','harness.py')
        if set(manifest['artifacts'])!=set(allowed):raise ValueError('Capability artifact set mismatch')
        for file,expected_hash in manifest['artifacts'].items():
            if file not in allowed or sha(folder/file)!=expected_hash: raise ValueError('Artifact integrity failure')
        if manifest['spec']['kind']=='coco_detection':
            from .media import image_request
            from .remote import infer_training
            endpoint=manifest['endpoint']
            request=dict(image_request(endpoint['contract'],input_path),**{key:value for key,value in endpoint.items() if key!='remote'})
            if expected_input_fingerprint and request['input_fingerprint']!=expected_input_fingerprint:
                raise ValueError('Input media changed after batch snapshot')
            if sample_id is not None: request['sample']['sample_id']=sample_id
            response=infer_training(endpoint['remote'],request,folder/'inference.py')
            self._verify_remote_prediction(endpoint,request,response)
            return {'task_id':name,'version':version,'kind':'coco_detection','output':response['output'],'acceptance':manifest['validation'],'sample_id':response['sample_id'],'device':response['device']}
        if expected_input_fingerprint and sha(input_path)!=expected_input_fingerprint:raise ValueError('Input changed after batch snapshot')
        process=subprocess.run([sys.executable,str(folder/'harness.py'),str(folder/'model.json'),str(Path(input_path).resolve())],capture_output=True,text=True,timeout=30)
        if process.returncode:
            raise ValueError('Inference adapter failed: '+(process.stderr.strip().splitlines() or ['exit '+str(process.returncode)])[-1])
        output=process.stdout
        return {'task_id':name,'version':version,'kind':manifest['spec']['kind'],'output':json.loads(output),'acceptance':manifest['validation']}
