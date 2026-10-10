"""Linux-only isolated serving crash probe; synthetic adapter, no model/GPU."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def main():
    request=json.load(sys.stdin)
    base=Path(request['workspace']).resolve()
    if not base.is_absolute() or base==Path('/'):raise ValueError('Dedicated workspace required')
    root=base/'serving-fault-fixtures'/uuid.uuid4().hex;root.mkdir(parents=True)
    processes=[]
    def timeout(*_):raise TimeoutError('Serving fault probe deadline')
    signal.signal(signal.SIGALRM,timeout);signal.alarm(50)
    try:
        (root/'vision_rsi').mkdir();(root/'vision_rsi/__init__.py').write_text('')
        (root/'vision_rsi/detector.py').write_text('COCO_IDS = '+repr(tuple(request['category_ids'])))
        (root/'serving.py').write_bytes(base64.b64decode(request['serving_source']))
        worker=root/'worker.py';worker.write_text('import json,sys; from serving import step; print(json.dumps(step(json.load(sys.stdin))))')
        data=root/'data';(data/'annotations').mkdir(parents=True);(data/'val2017').mkdir()
        images=[{'id':i,'file_name':str(i)+'.bin','width':2,'height':2} for i in (1,2,3)]
        for image in images:(data/'val2017'/image['file_name']).write_bytes(b'fixture-only')
        annotations=data/'annotations/instances_val2017.json'
        annotations.write_text(json.dumps({'images':images,'categories':[{'id':i} for i in request['category_ids']],'annotations':[]}))
        adapter=b"""import hashlib,time
from pathlib import Path
def load_runtime(request):
 return {'request':request,'serving_runtime_sha256':'f'*64,'serving_runtime':{'fixture':True}}
def predict(runtime,raw,sample):
 root=Path(runtime['request']['workspace'])
 calls=root/'calls';calls.mkdir(exist_ok=True)
 with (calls/str(time.time_ns())).open('x') as stream:stream.write(sample['sample_id'])
 if (root/'block_once').exists():
  (root/'block_once').unlink();(root/'entered_prediction').write_text('ready');time.sleep(120)
 return {'width':2,'height':2,'image_sha256':hashlib.sha256(raw).hexdigest(),'output':{'detections':[]}}
"""
        endpoint={'recipe':{'coco_root':str(data),'val_annotations_sha256':hashlib.sha256(annotations.read_bytes()).hexdigest(),'fixture':True},
                  'contract':{'inputs':{'image':{'type':'image'}},'acceptance':{'threshold':60}},'serving_runtime_sha256':'f'*64}
        job={'workspace':str(root),'endpoint':endpoint,'wall_seconds_budget':120,'chunk_size':1,
             'adapter_source_base64':base64.b64encode(adapter).decode(),'inference_adapter_sha256':hashlib.sha256(adapter).hexdigest()}
        def start(value):
            process=subprocess.Popen([sys.executable,str(worker)],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            processes.append(process);process.stdin.write(json.dumps(value));process.stdin.close();process.stdin=None
            return process
        def run(value):
            process=start(value);out,err=process.communicate(timeout=15)
            return process.returncode,out,err
        def crash():
            marker=root/'entered_prediction'
            if marker.exists():marker.unlink()
            (root/'block_once').write_text('fixture trigger')
            process=start(job);deadline=time.monotonic()+10
            while not marker.exists():
                if process.poll() is not None:raise RuntimeError(process.stderr.read())
                if time.monotonic()>=deadline:raise TimeoutError('Prediction not reached')
                time.sleep(.05)
            assert process.poll() is None
            active_state=next((root/'serving').glob('*/state.json'))
            before_concurrent=active_state.read_bytes()
            code,out,err=run(job)
            assert code!=0 and 'already active' in err
            assert active_state.read_bytes()==before_concurrent
            process.kill();process.communicate(timeout=5)
            assert process.returncode==-signal.SIGKILL
        crash()
        state_path=next((root/'serving').glob('*/state.json'))
        first=json.loads(state_path.read_text());assert first['spent_wall_seconds']==60 and not first['items']
        code,out,err=run(job);assert code==0,err
        result=json.loads(out);second=json.loads(state_path.read_text())
        assert result['status']=='pending' and result['processed_images']==1
        assert 60<=second['spent_wall_seconds']<70
        saved=next((root/'serving').glob('*/1.json'));saved_bytes=saved.read_bytes()
        code,out,err=run(dict(job,wall_seconds_budget=121))
        assert code!=0 and 'configuration changed' in err
        assert json.loads(state_path.read_text())==second
        crash();third=json.loads(state_path.read_text())
        assert third['spent_wall_seconds']==120 and len(third['items'])==1
        code,out,err=run(job);assert code==0,err
        assert json.loads(out)['status']=='budget_exhausted'
        assert saved.read_bytes()==saved_bytes
        sample_calls=dict(Counter(path.read_text() for path in (root/'calls').iterdir()))
        assert sample_calls=={'val-1':2,'val-2':1},sample_calls
        preserved_state=state_path.read_bytes()
        for invalid in (-1,False,float('nan'),float('inf'),'0',None):
            broken=json.loads(preserved_state);broken['spent_wall_seconds']=invalid
            state_path.write_text(json.dumps(broken));bad_bytes=state_path.read_bytes()
            code,out,err=run(job)
            assert code!=0 and 'budget accounting state' in err
            assert state_path.read_bytes()==bad_bytes
        broken=json.loads(preserved_state);broken['items']['1']['file_sha256']='bad'
        state_path.write_text(json.dumps(broken));bad_bytes=state_path.read_bytes()
        code,out,err=run(job)
        assert code!=0 and 'cache identity' in err
        assert state_path.read_bytes()==bad_bytes
        state_path.write_bytes(preserved_state)
        report={'status':'fixture_crash_resume_verified','directory':str(root),
                'first_kill_reserved_seconds':first['spent_wall_seconds'],'after_resume_spent_seconds':second['spent_wall_seconds'],
                'final_spent_seconds':third['spent_wall_seconds'],'saved_items':len(third['items']),
                'concurrent_requests_rejected':2,'invalid_spending_states_rejected':6,'invalid_cache_identity_rejected':True,
                'budget_increase_rejected':True,'cached_item_unchanged':True,'prediction_calls':sample_calls,'gpu_used':False,'model_inference':False,
                'quality_verified':False,'capability_registered':False,
                'serving_source_sha256':hashlib.sha256(base64.b64decode(request['serving_source'])).hexdigest()}
        (root/'probe-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        signal.alarm(0)
        for process in processes:
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream is not None:stream.close()


if __name__=='__main__':main()
