"""Explicit bounded CPU detector fixture; never trains on user COCO data or GPUs."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.remote import ssh_argv
from vision_rsi.runner import atomic_json

PROGRAM=r'''
import os,sys,json,io,hashlib,signal
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['TORCH_COMPILE_DISABLE']='1'
signal.alarm(50)
import torch
from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
request=json.load(sys.stdin)
with open(request['weights'],'rb') as stream:
 sha=hashlib.file_digest(stream,'sha256').hexdigest()
assert sha==request['weights_sha256'],'Pretrained weights hash mismatch'
weights=torch.load(request['weights'],map_location='cpu',weights_only=True)
images=[torch.linspace(0,1,3*64*64).reshape(3,64,64),torch.linspace(1,0,3*64*64).reshape(3,64,64)]
targets=[{'boxes':torch.tensor([[8.,8.,40.,48.]]),'labels':torch.tensor([1])},
         {'boxes':torch.tensor([[12.,10.,50.,52.]]),'labels':torch.tensor([1])}]
def new(state=None):
 torch.manual_seed(42)
 model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,num_classes=91,min_size=64,max_size=64)
 model.load_state_dict(weights if state is None else state['model'])
 opt=torch.optim.SGD(model.parameters(),lr=.0001,momentum=.9,weight_decay=.0001)
 if state is not None:opt.load_state_dict(state['optimizer']);torch.set_rng_state(state['rng'])
 model.train()
 return model,opt
def step(model,opt):
 values=model(images,targets)
 loss=sum(values.values());assert torch.isfinite(loss).item()
 opt.zero_grad();loss.backward()
 assert all(torch.isfinite(p.grad).all().item() for p in model.parameters() if p.grad is not None)
 opt.step()
 return {k:float(v.detach()) for k,v in values.items()}
model,opt=new();baseline=[step(model,opt),step(model,opt)]
expected={k:v.clone() for k,v in model.state_dict().items()}
momentum=[opt.state[p]['momentum_buffer'].clone() if p in opt.state else None for p in model.parameters()]
expected_rng=torch.get_rng_state().clone()
del model,opt
model,opt=new();first=step(model,opt)
stream=io.BytesIO();torch.save({'model':model.state_dict(),'optimizer':opt.state_dict(),'rng':torch.get_rng_state()},stream)
raw=stream.getvalue();del stream,model,opt
state=torch.load(io.BytesIO(raw),map_location='cpu',weights_only=True)
model,opt=new(state);second=step(model,opt)
checks={'loss_components_equal':[first,second]==baseline,
        'model_parameters_and_buffers_equal':all(torch.equal(v,expected[k]) for k,v in model.state_dict().items()),
        'optimizer_momentum_equal':all((p not in opt.state) if v is None else torch.equal(opt.state[p]['momentum_buffer'],v)
                                        for p,v in zip(model.parameters(),momentum)),
        'final_cpu_rng_equal':torch.equal(torch.get_rng_state(),expected_rng)}
assert all(checks.values()),checks
print(json.dumps({'passed':True,'fixture':True,'detector':'fasterrcnn_resnet50_fpn_v2','torch':torch.__version__,
 'weights_sha256':sha,'device':'cpu','batch_size':2,'image_size':[64,64],'total_fixture_training_steps':4,
 'continuous_loss_components':baseline,'restored_loss_components':[first,second],**checks,
 'checkpoint_sha256':hashlib.sha256(raw).hexdigest(),'gpu_used':False,'user_coco_data_used':False,
 'scope':'Two-step CPU detector fixture numerical resume; not production loop, DDP/CUDA, process death, quality or full COCO training.'}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true')
    parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; CPU detector fixture only')
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    request={key:config['training'][key] for key in ('weights','weights_sha256')}
    folder=Path('runs/resource-bootstrap')/('detector-cpu-resume-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    atomic_json(folder/'preregistered.json',{'request':request,'fixture':True,'remote_alarm_seconds':50,
        'probe_program_sha256':hashlib.sha256(PROGRAM.encode()).hexdigest(),
        'criteria':['exact loss components','exact model parameters/buffers','exact optimizer momentum','exact CPU RNG']})
    remote=config['remote']
    result=subprocess.run(ssh_argv(remote)+[shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(PROGRAM)],
                          input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=60)
    (folder/'stdout.txt').write_text(result.stdout,encoding='utf-8')
    (folder/'stderr.txt').write_text(result.stderr,encoding='utf-8')
    assert result.returncode==0,'Detector CPU probe failed; inspect retained logs in '+str(folder)
    evidence=json.loads(result.stdout.strip().splitlines()[-1])
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps({'directory':str(folder),**evidence},indent=2))


if __name__=='__main__':main()
