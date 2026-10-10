"""Explicit remote CPU fixture: freeze code, reject bad progress, accept good progress."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.detector import COCO_IDS
from vision_rsi.remote import deploy_training,ssh_argv
from vision_rsi.runner import atomic_json
from vision_rsi.training_preflight import check

SETUP=r'''
import os,json,hashlib,sys
from pathlib import Path
os.environ['CUDA_VISIBLE_DEVICES']=''
import torch
from PIL import Image
request=json.load(sys.stdin)
folder=Path(request['workspace'])/'training'/request['name']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
if request['action']=='setup':
 folder.mkdir(parents=True,exist_ok=False)
 root=folder/'dataset';(root/'annotations').mkdir(parents=True)
 for index,split in enumerate(('train','val'),1):
  (root/(split+'2017')).mkdir();Image.new('RGB',(64,64),(0,0,0)).save(root/(split+'2017')/'fixture.png')
  data={'categories':[{'id':i} for i in request['category_ids']],
        'images':[{'id':index,'file_name':'fixture.png','width':64,'height':64}],
        'annotations':[{'id':index,'image_id':index,'category_id':1,'bbox':[1,1,4,4],'area':16,'iscrowd':0}]}
  (root/'annotations'/('instances_'+split+'2017.json')).write_text(json.dumps(data))
 weights=folder/'fixture-weights.pt';torch.save({'fixture_tensor':torch.zeros(1)},weights)
 info={'directory':str(folder),'coco_root':str(root),'weights':str(weights),'weights_sha256':sha(weights),
       **{split+'_annotations_sha256':sha(root/'annotations'/('instances_'+split+'2017.json')) for split in ('train','val')}}
 checkpoint={'identity_hash':'f'*64,'epoch':0,'cursor':0,'step':1,
             'model':{'fixture_tensor':torch.zeros(1)},'optimizer':{},
             'rank_rng':[{'cpu':torch.get_rng_state(),'cuda':torch.get_rng_state()}]}
 torch.save(checkpoint,folder/'checkpoint.pt');torch.save(checkpoint,folder/'invalid-checkpoint.pt')
else:
 checkpoint=torch.load(folder/'checkpoint.pt',map_location='cpu',weights_only=True)
 checkpoint['step']=0;torch.save(checkpoint,folder/'checkpoint.pt')
 info={'directory':str(folder)}
info['checkpoint_sha256']=sha(folder/'checkpoint.pt')
print(json.dumps(info))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true');parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live_remote:parser.error('Explicit --live-remote required; CPU only, no training')
    remote=json.loads(Path(args.config).read_text(encoding='utf-8'))['remote']
    name='cpu-progress-probe-'+uuid.uuid4().hex
    folder=Path('runs/resource-bootstrap')/name;folder.mkdir(parents=True)
    atomic_json(folder/'preregistered.json',{'fixture':True,'remote_fixture_name':name,
        'cases':['inconsistent step rejected','corrected zero-step structure accepted'],
        'gpu_disabled':True,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Serialized synthetic checkpoint progress only; not valid detector/optimizer/CUDA RNG or numerical training evidence.'})
    def action(mode):
        result=subprocess.run(ssh_argv(remote)+[shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(SETUP)],
            input=json.dumps({'workspace':remote['workspace'],'name':name,'action':mode,'category_ids':COCO_IDS}),
            capture_output=True,text=True,timeout=45)
        if result.returncode:raise RuntimeError('Remote fixture setup failed: '+result.stderr[-1000:])
        return json.loads(result.stdout)
    resources=action('setup');atomic_json(folder/'resources.json',resources)
    recipe={'detector':'torchvision_fasterrcnn_resnet50_fpn_v2','epochs':1,'batch_size_per_gpu':2,
            'seed':42,'checkpoint_steps':1,'world_size':1,'min_size':64,'max_size':64,
            'learning_rate':.001,'weight_decay':.0001,'fixture':True,'acceptance_threshold':60,
            **{key:value for key,value in resources.items() if key not in ('directory','checkpoint_sha256')}}
    plan={'recipe':recipe,'contract':{'fixture':True},'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].joinpath('vision_rsi').glob('*.py')}}
    deployment=deploy_training(remote,plan);atomic_json(folder/'deployment.json',deployment)
    rejection=None
    try:check(remote,deployment,plan,checkpoint={'directory':resources['directory'],'sha256':resources['checkpoint_sha256']})
    except RuntimeError as error:
        rejection={'error_type':type(error).__name__,'inconsistent_progress_rejected':'inconsistent with frozen dataset' in str(error)}
    atomic_json(folder/'invalid-result.json',rejection)
    assert rejection and rejection['inconsistent_progress_rejected'],'Unexpected rejection result; fixture evidence retained'
    corrected=action('correct')
    report=check(remote,deployment,plan,checkpoint={'directory':corrected['directory'],'sha256':corrected['checkpoint_sha256']})
    atomic_json(folder/'valid-result.json',report)
    evidence={'fixture':True,'passed':True,'directory':str(folder.resolve()),'deployment':deployment['bundle_id'],
              'invalid_rejected':True,'valid_progress_checked':report['checkpoint_progress_checked'],
              'train_images':report['train_images'],'validation_images':report['validation_images'],
              'gpu_used':False,'training_started':False,'model_quality_verified':False,
              'scope':'Actual frozen-bundle remote CPU preflight on synthetic Torch checkpoint; not model weights/optimizer/CUDA RNG validity or 8-GPU numerical resume.'}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
