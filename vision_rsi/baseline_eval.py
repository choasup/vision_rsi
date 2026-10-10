"""Resumable CPU evaluation of the fixed public baseline; never registers a capability."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .campaign import lease
from .coco_eval import evaluate, file_sha
from .detector import detections
from .resource_verify import verify_images
from .runner import atomic_json, digest


def cached_prediction(path, identity, image_id, image_sha, predict):
    """Bind cached outputs to this exact model, source and input bytes."""
    path=Path(path)
    if path.exists():
        saved=json.loads(path.read_text())
        checksum=saved.pop('record_sha256',None)
        if checksum!=digest(saved) or saved['identity']!=identity or saved['image_id']!=image_id or saved['image_sha256']!=image_sha:
            raise ValueError('Cached baseline prediction changed or belongs to another input')
        return saved['detections']
    rows=predict()
    saved={'identity':identity,'image_id':image_id,'image_sha256':image_sha,'detections':rows}
    saved['record_sha256']=digest(saved)
    atomic_json(path,saved)
    return rows


def run(root, weights, weights_sha256, annotation_sha256, image_manifest_sha256, output, seconds):
    if type(seconds) is not int or not 1<=seconds<=240:raise ValueError('CPU step must be 1..240 seconds')
    started=time.monotonic();deadline=started+seconds
    root=Path(root);weights=Path(weights);output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    with lease(output/'baseline.lock'):
        sources={p.name:file_sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
        identity=digest({'root':str(root.resolve()),'weights':str(weights.resolve()),
                         'weights_sha256':weights_sha256,'annotation_sha256':annotation_sha256,
                         'image_manifest_sha256':image_manifest_sha256,'sources':sources,
                         'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','min_size':800,'max_size':1333})
        state_path=output/'state.json'
        if state_path.exists() and json.loads(state_path.read_text())['identity']!=identity:
            raise ValueError('Frozen baseline evaluation identity changed')
        if file_sha(weights)!=weights_sha256 or not weights_sha256.startswith('dd69338a'):
            raise ValueError('Fixed public baseline weights mismatch')
        verified=verify_images(root,'val',5000)
        if verified['annotation_sha256']!=annotation_sha256 or verified['image_manifest_sha256']!=image_manifest_sha256:
            raise ValueError('Frozen validation dataset mismatch')
        data=json.loads((root/'annotations/instances_val2017.json').read_text())
        images=sorted(data['images'],key=lambda row:row['id'])
        import torch,torchvision
        if torch.__version__!='2.6.0+cu124' or torchvision.__version__!='0.21.0+cu124':
            raise ValueError('Pinned baseline runtime required')
        torch.set_num_threads(4)
        from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
        from torchvision.transforms.functional import pil_to_tensor
        from PIL import Image
        model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,num_classes=91,min_size=800,max_size=1333)
        model.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True),strict=True);model.eval()
        rows=[];coverage=[]
        for item in images:
            path=root/'val2017'/item['file_name'];image_sha=file_sha(path)
            cache=output/(str(item['id'])+'.json')
            if not cache.exists() and time.monotonic()>=deadline:break
            def predict():
                with Image.open(path) as image:
                    tensor=pil_to_tensor(image.convert('RGB')).float()/255
                with torch.inference_mode():prediction=model([tensor])[0]
                return detections(prediction['boxes'].tolist(),prediction['labels'].tolist(),prediction['scores'].tolist())
            result=cached_prediction(cache,identity,item['id'],image_sha,predict)
            rows.extend(dict(row,image_id=item['id']) for row in result);coverage.append(item['id'])
        summary={'identity':identity,'processed_images':len(coverage),'total_images':5000,
                 'status':'partial','gpu_used':False,'training_started':False,'capability_registered':False,
                 'coco_evaluated':False,'elapsed_seconds':time.monotonic()-started}
        if len(coverage)==5000 and time.monotonic()<deadline:
            atomic_json(output/'predictions.json',rows);atomic_json(output/'coverage.json',coverage)
            report=evaluate(root/'annotations/instances_val2017.json',output/'predictions.json',output/'coverage.json',
                            expected_annotation_sha256=annotation_sha256,include_errors=True)
            atomic_json(output/'metrics.json',report)
            summary.update(status='evaluated',coco_evaluated=True,metrics_sha256=file_sha(output/'metrics.json'))
        atomic_json(state_path,summary)
        return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','weights','weights-sha256','annotation-sha256','image-manifest-sha256','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--seconds',type=int,default=240)
    args=parser.parse_args(argv)
    print(json.dumps(run(**vars(args)),indent=2))


if __name__=='__main__':main()
