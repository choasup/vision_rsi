"""Bounded foreground continuation of one frozen CPU baseline evaluation."""
import argparse
import json
from pathlib import Path
import re
import time

from .campaign import lease
from .remote import job_request
from .runner import atomic_json, digest


def controls():
    import hashlib
    root=Path(__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('baseline_watch.py','remote.py','jobs.py','runner.py','campaign.py')}


def binding(record, maximum):
    if type(maximum) is not int or not 1<=maximum<=256:raise ValueError('Total step limit must be 1..256')
    match=re.fullmatch(r'(baseline-cpu-[a-z0-9]+)-a([0-9]+)',record['job_id'])
    if not match:raise ValueError('Invalid CPU baseline job ID')
    spec=record['spec']
    if spec.get('gpu_devices')!=[] or spec.get('gpu_hours_budget')!=0 or spec.get('timeout_seconds')!=300:
        raise ValueError('Only bounded 300s zero-GPU baseline steps supported')
    context=record['observation_context']
    if not isinstance(context.get('identity'),str) or len(context['identity'])!=64:
        raise ValueError('Frozen evaluation identity required')
    return {'prefix':match[1],'spec':spec,'remote':record['remote'],'context':context,
            'max_steps':maximum,'controls':controls()}


def advance(active, maximum, allow_submit=True, request=job_request):
    active=Path(active).resolve();root=active.parent;state_path=root/'baseline-watch.json'
    with lease(root/'baseline-watch.lock'):
        pointer=json.loads(active.read_text());record_path=Path(pointer['manifest']).resolve()
        if record_path.parent!=root:raise ValueError('Active record outside baseline record directory')
        record=json.loads(record_path.read_text());expected=binding(record,maximum)
        if state_path.exists():
            state=json.loads(state_path.read_text())
            if state['binding']!=expected:raise ValueError('Watch controls/configuration/step quota changed')
            if state['attempts'][-1]['job_id']!=record['job_id']:raise ValueError('Active baseline handle changed outside controller')
        else:
            attempts={}
            for path in root.glob('baseline-eval-job*.json'):
                item=json.loads(path.read_text())
                if binding(item,maximum)!=expected:raise ValueError('Historical baseline job binding differs')
                number=int(item['job_id'].rsplit('-a',1)[1])
                if number in attempts:raise ValueError('Duplicate historical job index')
                attempts[number]={'job_id':item['job_id'],'manifest':str(path.resolve())}
            if sorted(attempts)!=list(range(len(attempts))) or not attempts or attempts[max(attempts)]['job_id']!=record['job_id']:
                raise ValueError('Missing or noncontiguous baseline history')
            state={'binding':expected,'attempts':[attempts[i] for i in sorted(attempts)]}
            # Import historical jobs rather than treating a new watcher as a fresh quota.
            for attempt in state['attempts'][:-1]:
                observed=request(record['remote'],'status',attempt['job_id'])
                if observed.get('spec_hash')!=digest(record['spec']) or observed.get('status')!='completed':
                    raise ValueError('Historical baseline step is unsettled')
                if observed.get('gpu_count')!=0 or observed.get('gpu_hours')!=0:
                    raise ValueError('Historical CPU baseline allocation differs')
                attempt['terminal']=observed
            atomic_json(state_path,state)
        last=state['attempts'][-1]
        observed=request(record['remote'],'status',last['job_id'])
        if observed.get('spec_hash')!=digest(record['spec']):raise ValueError('Remote baseline specification changed')
        last['observation']=observed;atomic_json(state_path,state)
        if observed['status']!='completed':
            return {'status':observed['status'],'job_id':last['job_id'],'steps_reserved':len(state['attempts'])}
        if observed.get('gpu_count')!=0 or observed.get('gpu_hours')!=0:
            raise ValueError('CPU baseline allocation differs')
        report=json.loads(request(record['remote'],'logs',last['job_id'])['log'])
        if (report.get('identity')!=expected['context']['identity'] or report.get('gpu_used') is not False
                or report.get('training_started') is not False or report.get('capability_registered') is not False
                or report.get('total_images')!=5000 or type(report.get('processed_images')) is not int
                or not 0<=report['processed_images']<=5000):
            raise ValueError('Invalid completed baseline receipt')
        prior=max((a['report']['processed_images'] for a in state['attempts'] if 'report' in a),default=0)
        if report['processed_images']<prior:raise ValueError('Baseline coverage regressed')
        last['report']=report;last['terminal']=observed;atomic_json(state_path,state)
        if report['status']=='evaluated':
            if report.get('coco_evaluated') is not True or report['processed_images']!=5000:raise ValueError('Incomplete evaluation receipt')
            return {'status':'evaluated','job_id':last['job_id'],'capability_registered':False}
        if report['status']!='partial' or report.get('coco_evaluated') is not False:raise ValueError('Unexpected baseline state')
        if len(state['attempts'])>=maximum:return {'status':'step_budget_exhausted','job_id':last['job_id']}
        if not allow_submit:return {'status':'foreground_deadline','job_id':last['job_id']}
        number=len(state['attempts']);record['job_id']=expected['prefix']+'-a'+str(number)
        path=root/f'baseline-eval-job-a{number}.json';atomic_json(path,record)
        attempt={'job_id':record['job_id'],'manifest':str(path),'submission':'pending'}
        state['attempts'].append(attempt)
        # Journal both the intent and handle before a potentially uncertain network call.
        atomic_json(state_path,state);atomic_json(active,{'manifest':str(path),'job_id':record['job_id'],'submission_intent':True})
        response=request(record['remote'],'submit',record['job_id'],record['spec'])
        if response.get('spec_hash')!=digest(record['spec']):raise ValueError('Baseline submission spec mismatch')
        attempt['submission']='acknowledged';atomic_json(state_path,state)
        atomic_json(active,{'manifest':str(path),'job_id':record['job_id'],'submission':response})
        return {'status':'submitted','job_id':record['job_id'],'steps_reserved':len(state['attempts'])}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active',required=True)
    parser.add_argument('--max-steps',required=True,type=int)
    parser.add_argument('--seconds',required=True,type=int)
    parser.add_argument('--poll',type=int,default=30)
    args=parser.parse_args(argv)
    if not 1<=args.seconds<=86400 or not 5<=args.poll<=60:raise ValueError('Invalid foreground deadline/poll interval')
    deadline=time.monotonic()+args.seconds;previous=None
    while time.monotonic()<deadline:
        result=advance(args.active,args.max_steps,deadline-time.monotonic()>=305)
        changed=(result['status'],result['job_id'])
        if changed!=previous:print(json.dumps(result),flush=True);previous=changed
        if result['status'] not in ('running','queued','submitted'):return
        time.sleep(min(args.poll,max(0,deadline-time.monotonic())))
    print(json.dumps({'status':'foreground_deadline','remote_cancelled':False}),flush=True)


if __name__=='__main__':main()
