"""Serving-backend acceptance is separate from training-checkpoint acceptance."""
import math


def review_serving(manifest,report):
    endpoint=manifest['endpoint'];target=endpoint['contract']['acceptance']['threshold']
    if isinstance(target,bool) or not isinstance(target,(int,float)) or not math.isfinite(target) or not 0<=target<=100:
        raise ValueError('Invalid serving acceptance threshold')
    expected={'backend':'cpu','protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100',
              'pycocotools_version':'2.0.11','checkpoint_sha256':endpoint['checkpoint_sha256'],
              'training_identity_hash':endpoint['training_identity_hash'],
              'inference_adapter_sha256':manifest['artifacts']['inference.py'],
              'annotation_sha256':endpoint['recipe']['val_annotations_sha256']}
    runtime_sha=endpoint.get('serving_runtime_sha256')
    if not isinstance(runtime_sha,str) or len(runtime_sha)!=64 or any(c not in '0123456789abcdef' for c in runtime_sha):
        raise ValueError('Missing registered CPU serving runtime; re-register and evaluate backend')
    expected['serving_runtime_sha256']=runtime_sha
    for key,value in expected.items():
        if report.get(key)!=value:raise ValueError('Serving evaluation identity mismatch: '+key)
    if report.get('fixture') is not False or report.get('image_count')!=5000 or report.get('coverage_complete') is not True:
        raise ValueError('Full non-fixture serving evaluation required')
    score=report.get('metrics',{}).get('box_AP')
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=100:
        raise ValueError('Invalid serving AP')
    for key in ('predictions_sha256','coverage_sha256'):
        value=report.get(key)
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Missing serving artifact hash: '+key)
    if endpoint['contract']['acceptance']['direction']!='maximize' or score<target:
        raise ValueError('Serving backend does not meet original task acceptance')
    return {'status':'validated_serving_backend','passed':True,'box_AP':score,'threshold':target,
            'serving_backend':'cpu','serving_accuracy_verified':True,'capability_registered':True}
