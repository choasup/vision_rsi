"""Bounded, resumable full-validation evaluation of the actual CPU adapter."""
import base64
import fcntl
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import signal
import sys
import time


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)


def validate_state(state):
    """Malformed persisted costs are unknown evidence, never fresh budget."""
    spent=state.get('spent_wall_seconds')
    if isinstance(spent,bool) or not isinstance(spent,(int,float)) or not math.isfinite(spent) or spent<0:
        raise ValueError('Invalid serving budget accounting state; refusing to reset spending')
    items=state.get('items')
    if not isinstance(items,dict) or state.get('status') not in ('pending','processing','failed','evaluated'):
        raise ValueError('Invalid serving recovery state')
    for key,item in items.items():
        if (not isinstance(key,str) or not 1<=len(key)<=32 or not key.isascii() or not key.isdigit()
                or str(int(key))!=key or not isinstance(item,dict)):
            raise ValueError('Invalid serving cache index')
        for field in ('file_sha256','image_sha256'):
            value=item.get(field)
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Invalid serving cache identity')
    if 'total_images' in state:
        total=state['total_images']
        if type(total) is not int or total<1 or len(items)>total:raise ValueError('Invalid serving coverage state')


def step(request):
    endpoint=request['endpoint'];workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/':raise ValueError('Dedicated workspace required')
    budget=request['wall_seconds_budget'];count=request.get('chunk_size',10)
    if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or not 1<=budget<=86400:raise ValueError('Serving budget must be 1..86400 wall seconds')
    if isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=20:raise ValueError('Serving chunk_size must be 1..20')
    source=base64.b64decode(request['adapter_source_base64'],validate=True)
    source_sha=hashlib.sha256(source).hexdigest()
    if source_sha!=request['inference_adapter_sha256']:raise ValueError('Serving adapter identity differs')
    identity={'endpoint':endpoint,'inference_adapter_sha256':source_sha}
    evaluation_id=digest(identity)
    folder=Path(workspace)/'serving'/evaluation_id;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'evaluation.lock').open('a+') as lease:
        try:fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Serving evaluation is already active')
        state_path=folder/'state.json'
        if state_path.exists():
            state=json.loads(state_path.read_text())
            if state['identity']!=identity or state['wall_seconds_budget']!=budget:raise ValueError('Serving evaluation configuration changed')
        else:state={'identity':identity,'wall_seconds_budget':budget,'spent_wall_seconds':0,'items':{},'status':'pending'}
        validate_state(state)
        if state['status']=='evaluated':
            report=folder/'serving-report.json'
            if sha(report)!=state['report_sha256']:raise ValueError('Serving report changed')
            return {'status':'evaluated','evaluation_id':evaluation_id,'report':json.loads(report.read_text())}
        remaining=budget-state['spent_wall_seconds']
        if remaining<10:return {'status':'budget_exhausted','evaluation_id':evaluation_id,'processed_images':len(state['items'])}
        finalizing=bool(state.get('total_images')) and len(state['items'])==state['total_images']
        reservation=min(300 if finalizing else 60,remaining)
        signal.alarm(max(1,math.ceil(reservation)))
        before=state['spent_wall_seconds'];state['spent_wall_seconds']+=reservation;state['status']='processing'
        save(state_path,state)  # A killed request conservatively consumes its full reservation.
        started=time.monotonic();deadline=started+max(.1,reservation-3)
        try:
            annotation=Path(endpoint['recipe']['coco_root'])/'annotations/instances_val2017.json'
            if sha(annotation)!=endpoint['recipe']['val_annotations_sha256']:raise ValueError('Serving validation annotations changed')
            data=json.loads(annotation.read_text());images=sorted(data['images'],key=lambda row:row['id'])
            fixture=endpoint['recipe'].get('fixture',False)
            state['total_images']=len(images)
            if not images or len({row['id'] for row in images})!=len(images) or any(isinstance(row['id'],bool) or not isinstance(row['id'],int) or row['id']<0 for row in images):raise ValueError('Invalid validation image IDs')
            if not fixture and len(images)!=5000:raise ValueError('Full COCO val2017 required for serving validation')
            sys.path.insert(0,str(Path(workspace)/'runtime-coco-2.0.11'))
            scope={'__name__':'pinned_cpu_adapter'};exec(compile(source,'<pinned-serving-adapter>','exec'),scope)
            runtime=scope['load_runtime'](dict(endpoint,workspace=str(workspace)))
            from vision_rsi.detector import COCO_IDS
            if {row['id'] for row in data['categories']}!=set(COCO_IDS):raise ValueError('Serving validation requires 80 COCO categories')
            image_root=(Path(endpoint['recipe']['coco_root'])/'val2017').resolve()
            input_name=next(iter(endpoint['contract']['inputs']))
            processed=0
            for image in images:
                key=str(image['id']);path=folder/(key+'.json')
                if key in state['items']:
                    if not path.exists() or sha(path)!=state['items'][key]['file_sha256']:raise ValueError('Saved serving prediction changed')
                    continue
                if processed>=count or time.monotonic()>=deadline:break
                media=(image_root/image['file_name']).resolve()
                if not media.is_relative_to(image_root) or not media.is_file() or not 0<media.stat().st_size<=20*1024*1024:raise ValueError('Invalid validation media')
                raw=media.read_bytes()
                sample={'sample_id':'val-'+key,'inputs':{input_name:{'type':'image','uri':str(media)}}}
                prediction=scope['predict'](runtime,raw,sample)
                if prediction['width']!=image['width'] or prediction['height']!=image['height']:raise ValueError('Validation dimensions differ')
                row={'image_id':image['id'],'image_sha256':prediction['image_sha256'],'detections':prediction['output']['detections']}
                save(path,row);state['items'][key]={'file_sha256':sha(path),'image_sha256':prediction['image_sha256']}
                save(state_path,state);processed+=1
            if len(state['items'])==len(images) and time.monotonic()<deadline and (fixture or finalizing):
                predictions=[];coverage=[];image_fingerprints=[]
                for image in images:
                    key=str(image['id']);path=folder/(key+'.json')
                    if sha(path)!=state['items'][key]['file_sha256']:raise ValueError('Serving prediction changed during finalization')
                    row=json.loads(path.read_text());media=(image_root/image['file_name']).resolve()
                    if not media.is_relative_to(image_root) or sha(media)!=row['image_sha256']:raise ValueError('Serving images changed during evaluation')
                    coverage.append(image['id']);image_fingerprints.append([image['id'],row['image_sha256']])
                    predictions.extend(dict(item,image_id=image['id']) for item in row['detections'])
                save(folder/'predictions.json',predictions);save(folder/'coverage.json',coverage)
                from vision_rsi.coco_eval import evaluate
                report=evaluate(annotation,folder/'predictions.json',folder/'coverage.json',endpoint['contract']['acceptance']['threshold'],endpoint['recipe']['val_annotations_sha256'])
                report.update(backend='cpu',fixture=fixture,inference_adapter_sha256=source_sha,
                              checkpoint_sha256=endpoint['checkpoint_sha256'],training_identity_hash=endpoint['training_identity_hash'],
                              serving_runtime_sha256=runtime['serving_runtime_sha256'],serving_runtime=runtime['serving_runtime'],
                              validation_images_sha256=digest(image_fingerprints),evaluation_id=evaluation_id)
                save(folder/'serving-report.json',report);state.update(status='evaluated',report_sha256=sha(folder/'serving-report.json'))
                return {'status':'evaluated','evaluation_id':evaluation_id,'report':report}
            state['status']='pending'
            return {'status':'pending','evaluation_id':evaluation_id,'processed_images':len(state['items']),'total_images':len(images)}
        except Exception as error:
            state['status']='failed';state['error']=type(error).__name__+': '+str(error);raise
        finally:
            state['spent_wall_seconds']=before+time.monotonic()-started
            save(state_path,state)


if __name__=='__main__':
    signal.alarm(300)
    print(json.dumps(step(json.load(sys.stdin))))
