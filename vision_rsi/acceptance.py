"""Fail-closed acceptance review of Training receipts against frozen plans."""
import base64
import hashlib
import json
import math

from .runner import digest


def review(plan,receipt):
    reports={}
    for name in ('result.json','evaluation.json','progress.json'):
        row=receipt['reports'][name]
        content=base64.b64decode(row['base64'],validate=True)
        if hashlib.sha256(content).hexdigest()!=row['sha256']: raise ValueError('Collected report hash mismatch: '+name)
        reports[name]=json.loads(content)
    result=reports['result.json'];evaluation=reports['evaluation.json'];progress=reports['progress.json']
    identity=result['identity']
    if result['status']!='evaluated' or progress['status']!='evaluated': raise ValueError('Training did not complete evaluation')
    fingerprint=identity.get('image_contents_sha256')
    if not isinstance(fingerprint,str) or len(fingerprint)!=64 or any(c not in '0123456789abcdef' for c in fingerprint):
        raise ValueError('Missing frozen image content fingerprint')
    step=result.get('step')
    if isinstance(step,bool) or not isinstance(step,int) or step<=0: raise ValueError('No verified training steps in result')
    if result['identity_hash']!=digest(identity):raise ValueError('Training identity hash mismatch')
    if identity['recipe']!=plan['recipe'] or identity['sources']!=plan['source_hashes']:
        raise ValueError('Training recipe or code differs from frozen plan')
    hashes=receipt['artifact_hashes']
    if result['checkpoint_sha256']!=hashes['checkpoint.pt']: raise ValueError('Checkpoint hash mismatch')
    if result['evaluation_sha256']!=receipt['reports']['evaluation.json']['sha256']:raise ValueError('Evaluation report changed after training')
    if evaluation['predictions_sha256']!=hashes['predictions.json'] or evaluation['coverage_sha256']!=hashes['coverage.json']:
        raise ValueError('Predictions/coverage changed after evaluation')
    if evaluation['annotation_sha256']!=plan['recipe']['val_annotations_sha256']:raise ValueError('Validation dataset identity mismatch')
    if evaluation['protocol']!='pycocotools.COCOeval/bbox/defaults' or evaluation['metric_scale']!='0..100' or evaluation['pycocotools_version']!='2.0.11':
        raise ValueError('Unsupported evaluation protocol/version/scale')
    target=plan['contract']['acceptance']['threshold']
    score=evaluation['metrics']['box_AP']
    for name,value in [('threshold',target),('box_AP',score)]:
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:
            raise ValueError('Invalid acceptance '+name)
    if plan['contract']['acceptance']['direction']!='maximize' or plan['recipe']['acceptance_threshold']!=target:
        raise ValueError('Acceptance requirements changed')
    declared=evaluation['acceptance']
    if declared['threshold']!=target or declared['direction']!='maximize' or result['acceptance']!=declared:
        raise ValueError('Reported acceptance differs from task')
    reasons=[]
    if result.get('fixture') is not False or plan['recipe'].get('fixture') is not False: reasons.append('Synthetic/fixture results cannot validate a user capability')
    if evaluation.get('image_count')!=5000 or evaluation.get('coverage_complete') is not True or declared.get('eligible_for_coco_val2017') is not True:
        reasons.append('Full frozen COCO val2017 coverage not established')
    passed=not reasons and score>=target
    if declared.get('passed') is not passed: raise ValueError('Declared pass status contradicts measured evidence')
    if score<target:reasons.append('Measured box AP is below task requirement')
    diagnostics=None
    if 'error_analysis' in evaluation:
        from .coco_errors import brief
        diagnostics=brief(evaluation['error_analysis'])
        if sorted(row['category_id'] for row in evaluation['error_analysis']['categories'])!=evaluation.get('category_ids'):
            raise ValueError('Diagnostic categories differ from evaluated coverage')
        values=[row['box_AP'] for row in evaluation['error_analysis']['categories'] if row['box_AP'] is not None]
        if not values or abs(sum(values)/len(values)-score)>1e-6:raise ValueError('Category AP disagrees with overall AP')
    return {'status':'ready_for_registration' if passed else 'not_met','passed':passed,'box_AP':score,'threshold':target,
            'reasons':reasons,'checkpoint_sha256':hashes['checkpoint.pt'],
            'training_identity':identity,
            'error_summary':diagnostics,
            'capability_registered':False,'note':'Acceptance evidence review only; inference registration requires a working adapter.'}
