"""Remote CPU-only numerical fixture program, invoked explicitly by live probe."""
PROGRAM=r'''
import os,sys,json,io,hashlib,tempfile
from datetime import timedelta
os.environ['CUDA_VISIBLE_DEVICES']=''
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel as DDP
request=json.load(sys.stdin)
exec(request['iterator_source'],globals())
def worker(rank,rendezvous,queue):
 torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
 dist.init_process_group('gloo',init_method=rendezvous,rank=rank,world_size=2,timeout=timedelta(seconds=30))
 recipe={'seed':42,'batch_size_per_gpu':2}
 dataset=[(torch.tensor([i/17.,1.]),torch.tensor([i/34.])) for i in range(17)]
 def new(state=None):
  torch.manual_seed(71+rank)
  model=torch.nn.Sequential(torch.nn.Linear(2,4),torch.nn.Dropout(.3),torch.nn.Linear(4,1))
  opt=torch.optim.SGD(model.parameters(),lr=.01,momentum=.9)
  if state is not None:model.load_state_dict(state['model']);opt.load_state_dict(state['optimizer'])
  wrapped=DDP(model)
  if state is not None:torch.set_rng_state(state['rank_rng'][rank])
  return model,wrapped,opt
 def train(wrapped,opt,epoch_start=0,cursor_start=0,stop=None):
  trace=[]
  for epoch in range(epoch_start,3):
   for cursor,(xs,ys) in epoch_batches(dataset,recipe,epoch,rank,2,cursor_start if epoch==epoch_start else 0):
    loss=(wrapped(torch.stack(xs))-torch.stack(ys)).square().mean()
    opt.zero_grad();loss.backward();opt.step()
    trace.append([epoch,cursor,float(loss.detach())])
    if len(trace)==stop:return trace,epoch,cursor+1
  return trace,3,0
 model,wrapped,opt=new();full,_,_=train(wrapped,opt)
 expected_rng=torch.get_rng_state().clone()
 expected={k:v.clone() for k,v in model.state_dict().items()}
 momentum=[opt.state[p]['momentum_buffer'].clone() for p in model.parameters()]
 del wrapped,model,opt
 rows=[]
 for split in request['splits']:
  model,wrapped,opt=new();first,epoch,cursor=train(wrapped,opt,stop=split)
  states=[None,None];dist.all_gather_object(states,torch.get_rng_state())
  serialized=[None]
  if rank==0:
   stream=io.BytesIO();torch.save({'model':model.state_dict(),'optimizer':opt.state_dict(),
                                 'rank_rng':states,'epoch':epoch,'cursor':cursor},stream)
   serialized[0]=stream.getvalue()
  dist.broadcast_object_list(serialized,src=0)
  del wrapped,model,opt
  state=torch.load(io.BytesIO(serialized[0]),map_location='cpu',weights_only=True)
  model,wrapped,opt=new(state);rest,_,_=train(wrapped,opt,state['epoch'],state['cursor'])
  checks={'loss_and_batch_trace_equal':first+rest==full,
          'model_tensors_equal':all(torch.equal(v,expected[k]) for k,v in model.state_dict().items()),
          'optimizer_momentum_equal':all(torch.equal(opt.state[p]['momentum_buffer'],v) for p,v in zip(model.parameters(),momentum)),
          'final_cpu_rng_equal':torch.equal(torch.get_rng_state(),expected_rng)}
  rows.append({'split_step':split,**checks})
  assert all(checks.values()),(rank,rows[-1])
  del wrapped,model,opt
 gathered=[None,None];dist.all_gather_object(gathered,{'rank':rank,'total_steps':len(full),'cases':rows})
 if rank==0:queue.put(gathered)
 dist.destroy_process_group()
with tempfile.TemporaryDirectory(prefix='vision-rsi-cpu-ddp-') as directory:
 queue=mp.get_context('fork').SimpleQueue()
 mp.start_processes(worker,args=('file://'+directory+'/rendezvous',queue),nprocs=2,join=True,start_method='fork')
 ranks=queue.get()
print(json.dumps({'passed':True,'fixture':True,'torch':torch.__version__,'device':'cpu','backend':'gloo',
                  'world_size':2,'ranks':ranks,'iterator_sha256':hashlib.sha256(request['iterator_source'].encode()).hexdigest(),
                  'gpu_used':False,'scope':'Two-process CPU Linear/Dropout/SGD reconstruction, not detector/CUDA/NCCL or process-death recovery.'}))
'''
