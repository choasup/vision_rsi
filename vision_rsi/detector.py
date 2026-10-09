"""Torchvision detection execution adapter; smoke metrics are not COCO AP."""
import json
import math
from pathlib import Path
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


def dataset_check(root):
    if not root: return {'ready':False,'reason':'COCO root not configured'}
    root=Path(root)
    required=['train2017','val2017','annotations/instances_train2017.json','annotations/instances_val2017.json']
    missing=[name for name in required if not (root/name).exists()]
    result={'ready':not missing,'missing':missing,'root':str(root)}
    if not missing:
        data=json.loads((root/'annotations/instances_val2017.json').read_text())
        ids={category['id'] for category in data['categories']}
        result.update(validation_images=len(data['images']),category_ids_valid=ids==set(COCO_IDS))
        result['ready']=bool(data['images']) and ids==set(COCO_IDS)
    return result


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
