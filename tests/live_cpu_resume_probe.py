"""Explicit SSH CPU numerical fixture for the exact production batch iterator."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.coco_train import epoch_batches
from vision_rsi.remote import ssh_argv
from vision_rsi.runner import atomic_json

PROGRAM=r'''
import os,sys,json,io,hashlib
os.environ['CUDA_VISIBLE_DEVICES']=''
import torch
torch.set_num_threads(1)
torch.use_deterministic_algorithms(True)
request=json.load(sys.stdin)
exec(request['iterator_source'],globals())
recipe={'seed':42,'batch_size_per_gpu':2}
dataset=[(torch.tensor([i/17.,1.]),torch.tensor([i/34.])) for i in range(17)]
def new():
 torch.manual_seed(71)
 model=torch.nn.Sequential(torch.nn.Linear(2,4),torch.nn.Dropout(.3),torch.nn.Linear(4,1))
 return model,torch.optim.SGD(model.parameters(),lr=.01,momentum=.9)
def train(model,opt,start_epoch=0,start_cursor=0,stop=None):
 trace=[]
 for epoch in range(start_epoch,3):
  for cursor,(xs,ys) in epoch_batches(dataset,recipe,epoch,0,1,start_cursor if epoch==start_epoch else 0):
   loss=(model(torch.stack(xs))-torch.stack(ys)).square().mean()
   opt.zero_grad();loss.backward();opt.step()
   trace.append([epoch,cursor,float(loss.detach())])
   if len(trace)==stop:return trace,epoch,cursor+1
 return trace,3,0
baseline,opt=new();full,_,_=train(baseline,opt)
expected_rng=torch.get_rng_state().clone()
expected={k:v.clone() for k,v in baseline.state_dict().items()}
expected_momentum=[opt.state[p]['momentum_buffer'].clone() for p in baseline.parameters()]
rows=[]
for split in request['splits']:
 model,opt=new();first,epoch,cursor=train(model,opt,stop=split)
 stream=io.BytesIO();torch.save({'model':model.state_dict(),'optimizer':opt.state_dict(),
                              'rng':torch.get_rng_state(),'epoch':epoch,'cursor':cursor},stream)
 raw=stream.getvalue()
 model,opt=new();state=torch.load(io.BytesIO(raw),map_location='cpu',weights_only=True)
 model.load_state_dict(state['model']);opt.load_state_dict(state['optimizer']);torch.set_rng_state(state['rng'])
 rest,_,_=train(model,opt,state['epoch'],state['cursor'])
 checks={'loss_and_batch_trace_equal':first+rest==full,
         'model_tensors_equal':all(torch.equal(v,expected[k]) for k,v in model.state_dict().items()),
         'optimizer_momentum_equal':all(torch.equal(opt.state[p]['momentum_buffer'],v) for p,v in zip(model.parameters(),expected_momentum)),
         'final_cpu_rng_equal':torch.equal(torch.get_rng_state(),expected_rng)}
 rows.append({'split_step':split,'checkpoint_sha256':hashlib.sha256(raw).hexdigest(),**checks})
 assert all(checks.values()),rows[-1]
print(json.dumps({'passed':True,'fixture':True,'torch':torch.__version__,'device':'cpu',
                  'total_steps':len(full),'cases':rows,'iterator_sha256':hashlib.sha256(request['iterator_source'].encode()).hexdigest(),
                  'gpu_used':False,'scope':'Single-process synthetic Linear/Dropout/SGD fixture, not detector or CUDA/DDP numerical proof.'}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true')
    parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; CPU fixture only')
    remote=json.loads(Path(args.config).read_text(encoding='utf-8'))['remote']
    request={'iterator_source':inspect.getsource(epoch_batches),'splits':[1,8,9,10,26,27]}
    folder=Path('runs/resource-bootstrap')/('cpu-numerical-resume-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    atomic_json(folder/'preregistered.json',request)
    result=subprocess.run(ssh_argv(remote)+[shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(PROGRAM)],
                          input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=60)
    (folder/'stdout.txt').write_text(result.stdout,encoding='utf-8')
    (folder/'stderr.txt').write_text(result.stderr,encoding='utf-8')
    assert result.returncode==0,'Remote CPU probe failed; inspect retained logs'
    evidence=json.loads(result.stdout)
    assert evidence['iterator_sha256']==hashlib.sha256(request['iterator_source'].encode()).hexdigest()
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps({'directory':str(folder),**evidence},indent=2))


if __name__=='__main__':main()
