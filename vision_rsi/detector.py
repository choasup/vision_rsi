"""Torchvision detection execution adapter; smoke metrics are not COCO AP."""
import json
import math
from pathlib import Path
import stat
import sys
import time

# COCO's 80 category IDs occupy a sparse subset of 1..90, not contiguous 1..80.
COCO_IDS = (1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,20,21,22,23,24,25,27,28,31,32,33,34,35,36,37,38,39,40,41,42,43,44,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,67,70,72,73,74,75,76,77,78,79,80,81,82,84,85,86,87,88,89,90)


def detections(boxes, labels, scores):
    if not len(boxes)==len(labels)==len(scores): raise ValueError('Detection lengths mismatch')
    output=[]
    for box,label,score in zip(boxes,labels,scores):
        if label not in COCO_IDS: continue
        if len(box)!=4 or any(not math.isfinite(v) for v in box) or not math.isfinite(score) or not 0<=score<=1:
            raise ValueError('Invalid prediction')
        x0,y0,x1,y1=box
        if x1<=x0 or y1<=y0: raise ValueError('Invalid detection box')
        output.append({'bbox':[x0,y0,x1-x0,y1-y0],'category_id':label,'score':score})
    return output


def split_check(root, split, expected_images):
    root=Path(root)
    annotation=root/'annotations'/f'instances_{split}2017.json'
    directory=root/f'{split}2017'
    try:
        data=json.loads(annotation.read_text())
        resolved_directory=directory.resolve(strict=True)
        categories=data['categories'];images=data['images'];annotations=data['annotations']
        category_ids=[row['id'] for row in categories]
        if len(category_ids)!=80 or set(category_ids)!=set(COCO_IDS):
            raise ValueError('Expected exactly 80 COCO category IDs')
        ids=[row['id'] for row in images]
        if len(ids)!=expected_images or len(set(ids))!=len(ids) or any(type(i) is not int or i<0 for i in ids):
            raise ValueError('Unexpected image count or duplicate/invalid image IDs')
        image_ids=set(ids);names=set()
        for image in images:
            name=image['file_name']
            if not isinstance(name,str) or not name or Path(name).name!=name or chr(92) in name or ':' in name:
                raise ValueError('Invalid image filename')
            if name in names:raise ValueError('Duplicate image filename')
            names.add(name)
            # Names are flat, so a regular non-reparse file under the resolved
            # directory cannot traverse elsewhere. Avoid repeated Windows
            # realpath calls for each of the 118287 training files.
            path=resolved_directory/name
            info=path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_size==0
                    or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024)):
                raise ValueError('Missing, empty or escaping image file')
            if any(type(image[k]) is not int or image[k]<=0 for k in ('width','height')):
                raise ValueError('Invalid image dimensions')
        annotation_ids=set();zero_area_annotations=[]
        for row in annotations:
            if type(row['id']) is not int or row['id'] in annotation_ids:
                raise ValueError('Duplicate/invalid annotation ID')
            annotation_ids.add(row['id'])
            if row['image_id'] not in image_ids or row['category_id'] not in COCO_IDS:
                raise ValueError('Unknown annotation image/category')
            box=row['bbox']
            if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box) or box[2]<0 or box[3]<0:
                raise ValueError('Invalid annotation box')
            if box[2]==0 or box[3]==0:
                # Official train2017 contains two such annotations. Preserve
                # the original bytes; CocoImages excludes degenerate targets.
                if split!='train':raise ValueError('Invalid annotation box')
                zero_area_annotations.append(row['id'])
        if directory.resolve(strict=True)!=resolved_directory:
            raise ValueError('Image directory changed during coverage check')
        import hashlib
        return {'ready':True,'images':len(images),'annotations':len(annotations),
                'annotation_sha256':hashlib.sha256(annotation.read_bytes()).hexdigest(),
                'image_ids':ids,'pixel_decode_verified':False,
                'zero_area_annotation_ids':sorted(zero_area_annotations),
                'training_box_policy':'clip to image bounds; exclude crowd and nonpositive clipped area'}
    except (OSError,ValueError,KeyError,TypeError) as error:
        return {'ready':False,'reason':str(error)[:300]}


def dataset_check(root):
    if not root:return {'ready':False,'evaluation_ready':False,'reason':'COCO root not configured'}
    train=split_check(root,'train',118287);val=split_check(root,'val',5000)
    overlap=bool(set(train.get('image_ids',[]))&set(val.get('image_ids',[])))
    train.pop('image_ids',None);val.pop('image_ids',None)
    return {'ready':train['ready'] and val['ready'] and not overlap,
            'evaluation_ready':val['ready'],'training_ready':train['ready'] and val['ready'] and not overlap,
            'root':str(root),'splits':{'train':train,'val':val},'split_overlap':overlap,
            'limitation':'File coverage and annotation checks only; pixel decoding and model evaluation remain separate.'}


def smoke():
    import torch
    import torchvision
    from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
    if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable')
    torch.manual_seed(42);torch.cuda.manual_seed_all(42)
    device=torch.device('cuda:0');torch.cuda.set_device(device);torch.cuda.init();torch.cuda.reset_peak_memory_stats(device)
    start=time.monotonic()
    model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,num_classes=91,
                                   min_size=64,max_size=64,rpn_pre_nms_top_n_train=64,rpn_post_nms_top_n_train=32,
                                   rpn_pre_nms_top_n_test=64,rpn_post_nms_top_n_test=32,box_detections_per_img=10).to(device)
    images=[torch.rand(3,64,64,device=device) for _ in range(2)]
    targets=[{'boxes':torch.tensor([[10.,10.,40.,45.]],device=device),'labels':torch.tensor([1],device=device)} for _ in images]
    model.train();optimizer=torch.optim.SGD(model.parameters(),lr=0.001)
    losses=model(images,targets);loss=sum(losses.values())
    if not torch.isfinite(loss): raise RuntimeError('Nonfinite detection loss')
    optimizer.zero_grad();loss.backward()
    if not all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None): raise RuntimeError('Nonfinite gradients')
    optimizer.step();model.eval()
    with torch.no_grad(): prediction=model(images[:1])[0]
    result=detections(prediction['boxes'].cpu().tolist(),prediction['labels'].cpu().tolist(),prediction['scores'].cpu().tolist())
    torch.cuda.synchronize();elapsed=time.monotonic()-start
    return {'status':'smoke_passed','adapter':'torchvision_fasterrcnn_resnet50_fpn_v2','torch':torch.__version__,
            'torchvision':torchvision.__version__,'gpu':torch.cuda.get_device_name(device),'gpu_count':1,
            'elapsed_seconds':elapsed,'allocated_gpu_hours':elapsed/3600,'peak_allocated_bytes':torch.cuda.max_memory_allocated(device),
            'losses':{key:float(value.detach()) for key,value in losses.items()},'output':{'detections':result},
            'training_steps':1,'synthetic_images':True,'pretrained_weights':False,'coco_evaluated':False,
            'limitation':'Random initialization on random images; tests forward/backward/inference, not detection quality.'}


if __name__=='__main__':
    request=json.load(sys.stdin)
    if request['action']=='smoke': result=smoke()
    elif request['action']=='dataset-check': result=dataset_check(request.get('coco_root'))
    else: raise ValueError('Unsupported detector action')
    print(json.dumps(result))
