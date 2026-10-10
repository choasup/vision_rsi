"""Pinned torchvision COCO baseline: real data, checkpoints and full evaluation.

No implicit downloads or random initialization in production. Execute with
python -m torch.distributed.run --standalone --nproc-per-node=N -m
vision_rsi.coco_train --recipe recipe.json --output run-directory.
"""
import argparse
from datetime import timedelta
import json
import importlib.metadata
import math
import os
from pathlib import Path, PurePosixPath
import signal

from .coco_eval import evaluate, file_sha
from .detector import COCO_IDS, detections
from .runner import atomic_json, digest


def validate_recipe(recipe,path_flavor='native'):
    allowed={'detector','coco_root','weights','weights_sha256','train_annotations_sha256','val_annotations_sha256','epochs','batch_size_per_gpu','seed','checkpoint_steps','world_size','min_size','max_size','learning_rate','weight_decay','fixture','acceptance_threshold'}
    if not isinstance(recipe,dict) or set(recipe)-allowed: raise ValueError('Unknown training recipe fields')
    if recipe.get('detector')!='torchvision_fasterrcnn_resnet50_fpn_v2':
        raise ValueError('Unsupported frozen baseline detector')
    if path_flavor not in ('native','posix'):raise ValueError('Unknown execution path flavor')
    path_type=PurePosixPath if path_flavor=='posix' else Path
    for key in ('coco_root','weights'):
        if not isinstance(recipe.get(key),str) or not path_type(recipe[key]).is_absolute() or '..' in path_type(recipe[key]).parts:
            raise ValueError(key+' requires absolute execution-host path')
    for key in ('weights_sha256','train_annotations_sha256','val_annotations_sha256'):
        value=recipe.get(key)
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError(key+' requires frozen lowercase SHA256')
    for key,low,high in [('epochs',1,10000),('batch_size_per_gpu',1,64),('seed',0,2**31-1),('checkpoint_steps',1,100000),('world_size',1,8),('min_size',64,2048),('max_size',64,4096)]:
        value=recipe.get(key)
        if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
            raise ValueError('Invalid recipe '+key)
    if recipe['max_size']<recipe['min_size']: raise ValueError('max_size smaller than min_size')
    threshold=recipe.get('acceptance_threshold',60)
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=100:
        raise ValueError('Invalid recipe acceptance_threshold')
    for key in ('learning_rate','weight_decay'):
        value=recipe.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (key=='learning_rate' and value==0):
            raise ValueError('Invalid recipe '+key)
    if not isinstance(recipe.get('fixture',False),bool): raise ValueError('fixture must be boolean')
    return recipe


class CocoImages:
    """Map COCO xywh annotations to torchvision xyxy; preserve sparse IDs."""
    def __init__(self, root, split, fixture=False):
        self.root=Path(root)/f'{split}2017'
        annotation_path=Path(root)/'annotations'/f'instances_{split}2017.json'
        self.data=json.loads(annotation_path.read_text())
        if {x['id'] for x in self.data['categories']}!=set(COCO_IDS): raise ValueError('Expected all 80 COCO category IDs')
        self.images=sorted(self.data['images'],key=lambda x:x['id'])
        ids=[x['id'] for x in self.images]
        if not ids or len(set(ids))!=len(ids): raise ValueError('Empty or duplicate image IDs')
        if not fixture and len(ids)!=(118287 if split=='train' else 5000): raise ValueError('Expected full COCO2017 split')
        self.annotations={i:[] for i in ids}
        self.zero_area_annotation_ids=[]
        for row in self.data['annotations']:
            if row['image_id'] not in self.annotations or row['category_id'] not in COCO_IDS:
                raise ValueError('Unknown annotation image/category')
            box=row['bbox']
            if (not isinstance(box,list) or len(box)!=4
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in box)
                    or box[2]<0 or box[3]<0):
                raise ValueError('Invalid annotation bbox')
            if box[2]==0 or box[3]==0:
                if split!='train':raise ValueError('Invalid annotation bbox')
                self.zero_area_annotation_ids.append(row['id'])
            self.annotations[row['image_id']].append(row)
        for image in self.images:
            path=(self.root/image['file_name']).resolve()
            if not path.is_relative_to(self.root.resolve()) or not path.is_file(): raise ValueError('Missing or escaping COCO image path')
    def __len__(self): return len(self.images)
    def __getitem__(self,index):
        import torch
        from PIL import Image
        from torchvision.transforms.functional import pil_to_tensor
        item=self.images[index]
        with Image.open(self.root/item['file_name']) as image:
            if image.size!=(item['width'],item['height']): raise ValueError('Image size differs from annotations')
            tensor=pil_to_tensor(image.convert('RGB')).float()/255
        boxes=[];labels=[]
        for row in self.annotations[item['id']]:
            if row.get('iscrowd',0): continue
            x,y,w,h=row['bbox']
            if any(not math.isfinite(v) for v in (x,y,w,h)): raise ValueError('Nonfinite annotation bbox')
            x0=max(0.,x);y0=max(0.,y);x1=min(float(item['width']),x+w);y1=min(float(item['height']),y+h)
            if x1>x0 and y1>y0:
                boxes.append([x0,y0,x1,y1]);labels.append(row['category_id'])
        return tensor,{'boxes':torch.tensor(boxes,dtype=torch.float32).reshape(-1,4),
                       'labels':torch.tensor(labels,dtype=torch.int64),'image_id':torch.tensor(item['id'])}


def preflight(recipe):
    validate_recipe(recipe)
    import torch,torchvision
    if torch.__version__!='2.6.0+cu124' or torchvision.__version__!='0.21.0+cu124':
        raise ValueError('Baseline requires pinned torch 2.6.0+cu124 / torchvision 0.21.0+cu124')
    if importlib.metadata.version('pycocotools')!='2.0.11': raise ValueError('Baseline requires pycocotools 2.0.11')
    root=Path(recipe['coco_root'])
    for path,expected in [(Path(recipe['weights']),recipe['weights_sha256'])]+[(root/'annotations'/f'instances_{split}2017.json',recipe[f'{split}_annotations_sha256']) for split in ('train','val')]:
        if file_sha(path)!=expected: raise ValueError('Frozen artifact hash mismatch: '+str(path))
    train=CocoImages(root,'train',recipe.get('fixture',False));val=CocoImages(root,'val',recipe.get('fixture',False))
    if not recipe.get('fixture',False) and {x['id'] for x in train.images}&{x['id'] for x in val.images}:
        raise ValueError('Training/validation image IDs overlap')
    return train,val


def run(recipe,output,resume=False):
    # Pinned torchvision ROIAlign has a deterministic Python fallback. Disable
    # lazy compilation so first-use compilation cannot consume an unbounded
    # part of an experiment budget. These settings precede CUDA initialization.
    os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
    os.environ['TORCH_COMPILE_DISABLE']='1'
    import torch
    import torch.distributed as dist
    from torch.nn.parallel import DistributedDataParallel
    from torch.utils.data import DataLoader,DistributedSampler
    from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    train,val=preflight(recipe)
    world=int(os.environ.get('WORLD_SIZE','1'));rank=int(os.environ.get('RANK','0'));local=int(os.environ.get('LOCAL_RANK','0'))
    if world!=recipe['world_size']: raise ValueError('Launcher GPU world size differs from frozen recipe')
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required for this baseline')
    torch.cuda.set_device(local);device=torch.device('cuda',local)
    if world>1: dist.init_process_group('nccl',timeout=timedelta(minutes=5))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    data_hash=__import__('hashlib').sha256()
    for dataset in (train,val):
        for image in dataset.images:
            data_hash.update(str(dataset.root.name).encode()+str(image['id']).encode()+file_sha(dataset.root/image['file_name']).encode())
    identity={'image_contents_sha256':data_hash.hexdigest(),'recipe':recipe,'sources':{p.name:file_sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))},'torch':torch.__version__}
    from .training_runtime import fingerprint
    identity['runtime']=fingerprint(torch,device)
    identity_hash=digest(identity)
    checkpoint_path=output/'checkpoint.pt'
    if checkpoint_path.exists() and not resume: raise ValueError('Checkpoint exists; explicitly resume or use another output')
    if resume and not checkpoint_path.exists(): raise ValueError('No checkpoint to resume')
    torch.manual_seed(recipe['seed']+rank);torch.cuda.manual_seed(recipe['seed']+rank)
    model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,num_classes=91,min_size=recipe['min_size'],max_size=recipe['max_size']).to(device)
    weights=torch.load(recipe['weights'],map_location='cpu',weights_only=True)
    model.load_state_dict(weights,strict=True)
    optimizer=torch.optim.SGD(model.parameters(),lr=recipe['learning_rate'],momentum=.9,weight_decay=recipe['weight_decay'])
    epoch_start=0;cursor_start=0;step=0;restore_rng=None
    if resume:
        checkpoint=torch.load(checkpoint_path,map_location='cpu',weights_only=True)
        if checkpoint['identity_hash']!=identity_hash: raise ValueError('Checkpoint data/recipe/code/runtime identity differs')
        model.load_state_dict(checkpoint['model']);optimizer.load_state_dict(checkpoint['optimizer'])
        epoch_start=checkpoint['epoch'];cursor_start=checkpoint['cursor'];step=checkpoint['step'];restore_rng=checkpoint['rank_rng'][rank]
    wrapped=DistributedDataParallel(model,device_ids=[local]) if world>1 else model
    if restore_rng is not None:
        torch.set_rng_state(restore_rng['cpu']);torch.cuda.set_rng_state(restore_rng['cuda'],device);restore_rng=None
    stop=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
    def save_checkpoint(epoch,cursor):
        rng={'cpu':torch.get_rng_state(),'cuda':torch.cuda.get_rng_state(device)}
        states=[None]*world
        if world>1: dist.all_gather_object(states,rng)
        else: states[0]=rng
        if rank==0:
            temp=checkpoint_path.with_suffix('.tmp')
            torch.save({'identity_hash':identity_hash,'model':model.state_dict(),'optimizer':optimizer.state_dict(),
                        'epoch':epoch,'cursor':cursor,'step':step,'rank_rng':states},temp)
            temp.replace(checkpoint_path)
            atomic_json(output/'progress.json',{'status':'training','epoch':epoch,'cursor':cursor,'step':step,'fixture':recipe.get('fixture',False),'identity_hash':identity_hash})
        if world>1: dist.barrier()
    interrupted=False
    for epoch in range(epoch_start,recipe['epochs']):
        sampler=DistributedSampler(train,num_replicas=world,rank=rank,seed=recipe['seed'],shuffle=True)
        sampler.set_epoch(epoch)
        loader=DataLoader(train,batch_size=recipe['batch_size_per_gpu'],sampler=sampler,num_workers=0,collate_fn=lambda rows:tuple(zip(*rows)),generator=torch.Generator().manual_seed(recipe['seed']+epoch))
        wrapped.train()
        for cursor,(images,targets) in enumerate(loader):
            if epoch==epoch_start and cursor<cursor_start: continue
            images=[image.to(device) for image in images]
            targets=[{key:value.to(device) for key,value in target.items()} for target in targets]
            loss=sum(wrapped(images,targets).values())
            finite=torch.tensor(int(torch.isfinite(loss).item()),device=device)
            if world>1: dist.all_reduce(finite,op=dist.ReduceOp.MIN)
            if not finite.item(): raise RuntimeError('Nonfinite training loss')
            optimizer.zero_grad();loss.backward()
            gradients_finite=torch.tensor(int(all(torch.isfinite(p.grad).all().item() for p in model.parameters() if p.grad is not None)),device=device)
            if world>1: dist.all_reduce(gradients_finite,op=dist.ReduceOp.MIN)
            if not gradients_finite.item(): raise RuntimeError('Nonfinite training gradients')
            optimizer.step();step+=1
            stopping=torch.tensor(int(stop[0]),device=device)
            if world>1: dist.all_reduce(stopping,op=dist.ReduceOp.MAX)
            if step%recipe['checkpoint_steps']==0 or stopping.item(): save_checkpoint(epoch,cursor+1)
            if rank==0: print(json.dumps({'epoch':epoch,'step':step,'loss':float(loss.detach()),'fixture':recipe.get('fixture',False)}),flush=True)
            if stopping.item(): interrupted=True;break
        if interrupted: break
        save_checkpoint(epoch+1,0)
    if world>1: dist.barrier();dist.destroy_process_group()
    if interrupted:
        result={'status':'interrupted','step':step,'checkpoint':str(checkpoint_path)}
        if rank==0: atomic_json(output/'progress.json',result)
        return result
    if rank!=0: return {'status':'training_completed_rank','rank':rank}
    atomic_json(output/'progress.json',{'status':'evaluating','step':step,'fixture':recipe.get('fixture',False)})
    model.eval();rows=[];coverage=[]
    with torch.no_grad():
        for index in range(len(val)):
            if stop[0]:
                result={'status':'interrupted_evaluation','processed_images':len(coverage),'step':step}
                atomic_json(output/'progress.json',result);return result
            image,target=val[index];prediction=model([image.to(device)])[0]
            image_id=int(target['image_id']);coverage.append(image_id)
            for row in detections(prediction['boxes'].cpu().tolist(),prediction['labels'].cpu().tolist(),prediction['scores'].cpu().tolist()):
                rows.append(dict(row,image_id=image_id))
    atomic_json(output/'predictions.json',rows);atomic_json(output/'coverage.json',coverage)
    report=evaluate(Path(recipe['coco_root'])/'annotations/instances_val2017.json',output/'predictions.json',output/'coverage.json',recipe.get('acceptance_threshold',60),recipe['val_annotations_sha256'],include_errors=True)
    if recipe.get('fixture',False): report['acceptance'].update(passed=False,eligible_for_coco_val2017=False)
    atomic_json(output/'evaluation.json',report)
    result={'status':'evaluated','fixture':recipe.get('fixture',False),'identity':identity,'identity_hash':identity_hash,'step':step,
            'zero_area_training_annotation_ids':sorted(train.zero_area_annotation_ids),
            'checkpoint_sha256':file_sha(checkpoint_path),'evaluation_sha256':file_sha(output/'evaluation.json'),
            'acceptance':report['acceptance'],'capability_registered':False}
    atomic_json(output/'result.json',result)
    atomic_json(output/'progress.json',{'status':'evaluated','step':step,'acceptance':report['acceptance']})
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(prog='vision-rsi coco-train')
    parser.add_argument('--recipe',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--checkpoint-sha256')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args(argv)
    recipe=json.loads(Path(args.recipe).read_text(encoding='utf-8-sig'))
    if args.checkpoint_sha256:
        if not args.resume: raise ValueError('Checkpoint hash is only valid with --resume')
        if file_sha(Path(args.output)/'checkpoint.pt')!=args.checkpoint_sha256:
            raise ValueError('Resume checkpoint changed after inspection')
    if args.preflight:
        train,val=preflight(recipe);result={'status':'preflight_passed','train_images':len(train),'val_images':len(val),'training_performed':False}
    else:
        import fcntl
        output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
        lease=None
        if int(os.environ.get('RANK','0'))==0:
            lease=(output/'run.lock').open('a+')
            try: fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('Training output is in use by another process')
        try:
            if args.checkpoint_sha256 and file_sha(output/'checkpoint.pt')!=args.checkpoint_sha256:
                raise ValueError('Resume checkpoint changed while acquiring output lock')
            result=run(recipe,args.output,args.resume)
        finally:
            if lease: lease.close()
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
