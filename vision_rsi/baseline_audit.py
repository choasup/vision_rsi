"""Read-only audit of saved baseline outputs; does not infer AP from partial coverage."""
import argparse
import json
import math
from pathlib import Path

from .coco_eval import file_sha
from .detector import COCO_IDS, split_check
from .runner import digest


def audit(root, records, identity, annotation_sha256, expected_images=5000):
    root=Path(root);records=Path(records)
    if not records.is_dir() or records.is_symlink():raise ValueError('Existing cache directory required')
    checked=split_check(root,'val',expected_images)
    if not checked['ready'] or checked['annotation_sha256']!=annotation_sha256:
        raise ValueError('Audit dataset differs from frozen annotation identity')
    images={r['id']:r for r in json.loads((root/'annotations/instances_val2017.json').read_text())['images']}
    fingerprints=[];count=0
    for path in sorted(records.glob('[0-9]*.json')):
        if path.is_symlink():raise ValueError('Cache symlink refused')
        row=json.loads(path.read_text());saved_sha=row.pop('record_sha256',None)
        if set(row)!={'identity','image_id','image_sha256','detections'} or saved_sha!=digest(row):
            raise ValueError('Cache record integrity failure')
        image_id=row['image_id']
        if type(image_id) is not int or str(image_id)!=path.stem or image_id not in images or row['identity']!=identity:
            raise ValueError('Cache model/source/image identity mismatch')
        item=images[image_id]
        if file_sha(root/'val2017'/item['file_name'])!=row['image_sha256']:
            raise ValueError('Input image bytes changed')
        detections=row['detections']
        if not isinstance(detections,list) or len(detections)>100:raise ValueError('Invalid detection count')
        for detection in detections:
            if not isinstance(detection,dict) or set(detection)!={'bbox','category_id','score'}:
                raise ValueError('Unexpected detection fields')
            box=detection['bbox'];category=detection['category_id'];score=detection['score']
            if type(category) is not int or category not in COCO_IDS or type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1:
                raise ValueError('Invalid detection category/score')
            if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):
                raise ValueError('Invalid detection coordinates')
            x,y,w,h=box
            if min(x,y)<0 or min(w,h)<=0 or x+w>item['width']+.001 or y+h>item['height']+.001:
                raise ValueError('Detection outside image bounds')
        count+=len(detections);fingerprints.append([image_id,saved_sha])
    return {'identity':identity,'audited_images':len(fingerprints),'total_images':expected_images,
            'detections':count,'records_manifest_sha256':digest(fingerprints),
            'coverage_complete':len(fingerprints)==expected_images,'fixture':expected_images!=5000,
            'coco_evaluated':False,'quality_verified':False,'capability_registered':False,
            'read_only':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','records','identity','annotation-sha256'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    print(json.dumps(audit(**vars(args)),indent=2))


if __name__=='__main__':main()
