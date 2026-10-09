"""COCO bbox evaluation with explicit image coverage and pinned provenance."""
import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path

from .detector import COCO_IDS
from .runner import atomic_json


def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def evaluate(annotation_path, prediction_path, coverage_path, threshold=60, expected_annotation_sha256=None):
    """Evaluate all GT images, including images with no predictions.

    Coverage is a producer-written JSON list of processed image IDs, separate
    from detection rows: zero detections still counts as processed.
    """
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=100:
        raise ValueError('AP threshold must be in [0,100]')
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    annotations=json.loads(Path(annotation_path).read_text(encoding='utf-8-sig'))
    predictions=json.loads(Path(prediction_path).read_text(encoding='utf-8-sig'))
    coverage=json.loads(Path(coverage_path).read_text(encoding='utf-8-sig'))
    images=annotations['images'];categories=annotations['categories']
    ids=[x['id'] for x in images];category_ids=[x['id'] for x in categories]
    valid_id=lambda x:isinstance(x,int) and not isinstance(x,bool) and x>=0
    if not ids or any(not valid_id(x) for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Nonempty unique integer ground-truth image IDs required')
    if any(not valid_id(x) for x in category_ids) or len(category_ids)!=len(set(category_ids)):
        raise ValueError('Unique integer categories required')
    if not isinstance(coverage,list) or any(not valid_id(x) for x in coverage) or len(coverage)!=len(set(coverage)) or set(coverage)!=set(ids):
        raise ValueError('Inference coverage must match all annotation image IDs exactly')
    if not isinstance(predictions,list): raise ValueError('Predictions must be COCO result list')
    image_set=set(ids);category_set=set(category_ids)
    for row in predictions:
        if not isinstance(row,dict) or not valid_id(row.get('image_id')) or row['image_id'] not in image_set:
            raise ValueError('Unknown prediction image_id')
        if not valid_id(row.get('category_id')) or row['category_id'] not in category_set:
            raise ValueError('Unknown prediction category_id')
        bbox=row.get('bbox');score=row.get('score')
        if not isinstance(bbox,list) or len(bbox)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in bbox) or bbox[2]<=0 or bbox[3]<=0:
            raise ValueError('Prediction bbox must be finite xywh with positive size')
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
            raise ValueError('Prediction score must be finite in [0,1]')
    annotation_hash=file_sha(annotation_path)
    if expected_annotation_sha256 is not None and annotation_hash!=expected_annotation_sha256:
        raise ValueError('Annotation hash does not match frozen task dataset')
    log=io.StringIO()
    with contextlib.redirect_stdout(log):
        gt=COCO();gt.dataset=annotations;gt.createIndex()
        if predictions:
            # Older COCO files may omit info; loadRes expects it in recent versions.
            gt.dataset.setdefault('info',{})
            dt=gt.loadRes(predictions)
        else:
            dt=COCO();dt.dataset={'images':images,'categories':categories,'annotations':[]};dt.createIndex()
        evaluator=COCOeval(gt,dt,'bbox')
        evaluator.params.imgIds=sorted(ids)
        evaluator.evaluate();evaluator.accumulate();evaluator.summarize()
    names=['box_AP','AP50','AP75','AP_small','AP_medium','AP_large','AR1','AR10','AR100','AR_small','AR_medium','AR_large']
    metrics={name:(float(value)*100 if value>=0 else None) for name,value in zip(names,evaluator.stats)}
    # Shape checks are necessary but do not establish official provenance.
    eligible=(len(ids)==5000 and category_set==set(COCO_IDS) and expected_annotation_sha256 is not None)
    return {'protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100',
            'metrics':metrics,'image_count':len(ids),'prediction_count':len(predictions),
            'coverage_complete':True,'annotation_sha256':annotation_hash,
            'predictions_sha256':file_sha(prediction_path),'coverage_sha256':file_sha(coverage_path),
            'pycocotools_version':importlib.metadata.version('pycocotools'),
            'acceptance':{'threshold':threshold,'direction':'maximize','eligible_for_coco_val2017':eligible,
                          'passed':eligible and metrics['box_AP'] is not None and metrics['box_AP']>=threshold},
            'note':'Dataset hash must be independently pinned to official val2017; shape alone is not provenance. Fixture/subset scores cannot register a COCO capability.',
            'evaluation_log':log.getvalue()}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='vision-rsi evaluate-coco')
    parser.add_argument('--annotations',required=True)
    parser.add_argument('--predictions',required=True)
    parser.add_argument('--coverage',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--threshold',type=float,default=60)
    parser.add_argument('--annotation-sha256')
    args=parser.parse_args(argv)
    try:
        result=evaluate(args.annotations,args.predictions,args.coverage,args.threshold,args.annotation_sha256)
        atomic_json(Path(args.output),result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,OSError,ImportError) as error:
        parser.exit(1,type(error).__name__+': '+str(error)+'\n')
