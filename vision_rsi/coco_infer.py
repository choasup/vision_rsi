"""Standalone CPU inference for a pinned remote torchvision COCO checkpoint."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import signal
import warnings


def file_sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def cpu_runtime_identity(torch,torchvision):
    import importlib.metadata
    import platform
    packages={name:importlib.metadata.version(name) for name in ('torch','torchvision','pycocotools','Pillow','numpy')}
    modules={'torch':str(torch.__version__),'torchvision':str(torchvision.__version__)}
    if any(packages[name].partition('+')[0]!=modules[name].partition('+')[0] for name in modules):
        raise ValueError('CPU module and installed package versions differ')
    identity={'schema':'vision-rsi-cpu-runtime-v1','python':platform.python_version(),
              'platform':platform.platform(),'packages':packages,'modules':modules,
              'torch_build_sha256':hashlib.sha256(torch.__config__.show().encode()).hexdigest(),
              'cpu_threads':torch.get_num_threads(),'cpu_interop_threads':torch.get_num_interop_threads(),
              'deterministic_algorithms':torch.are_deterministic_algorithms_enabled(),
              'matmul_precision':torch.get_float32_matmul_precision()}
    encoded=json.dumps(identity,sort_keys=True,allow_nan=False).encode()
    return identity,hashlib.sha256(encoded).hexdigest()


def load_runtime(request):
    workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/':raise ValueError('Dedicated workspace required')
    root=Path(workspace).resolve();bundle=Path(request['bundle_directory']).resolve()
    if not bundle.is_relative_to(root/'releases'):raise ValueError('Inference bundle outside immutable releases')
    for name,expected in request['source_hashes'].items():
        path=bundle/'vision_rsi'/name
        if not path.resolve().is_relative_to(bundle) or file_sha(path)!=expected:raise ValueError('Pinned inference dependency changed')
    if json.loads((bundle/'recipe.json').read_text())!=request['recipe']:raise ValueError('Pinned recipe changed')
    checkpoint=Path(request['checkpoint']).resolve()
    if not checkpoint.is_relative_to(root/'training') or not checkpoint.is_file():raise ValueError('Checkpoint outside Training workspace')
    if file_sha(checkpoint)!=request['checkpoint_sha256']:raise ValueError('Registered checkpoint changed')
    sys.path.insert(0,str(bundle))
    from vision_rsi.contracts import validate_sample,validate_schema
    from vision_rsi.detector import detections
    contract=request['contract']
    if len(contract['inputs'])!=1 or any(field['type']!='image' for field in contract['inputs'].values()):raise ValueError('COCO adapter accepts exactly one image input')
    import torch,torchvision
    if torch.__version__!='2.6.0+cu124' or torchvision.__version__!='0.21.0+cu124':raise ValueError('Inference runtime differs from frozen baseline')
    torch.set_num_threads(4)
    serving_runtime,serving_runtime_sha=cpu_runtime_identity(torch,torchvision)
    if request.get('serving_runtime_sha256') is not None and request['serving_runtime_sha256']!=serving_runtime_sha:
        raise ValueError('CPU serving runtime differs from registered evaluation environment')
    from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
    from torchvision.transforms.functional import pil_to_tensor
    recipe=request['recipe']
    model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,num_classes=91,min_size=recipe['min_size'],max_size=recipe['max_size'])
    state=torch.load(checkpoint,map_location='cpu',weights_only=True)
    if state['identity_hash']!=request['training_identity_hash']:raise ValueError('Checkpoint Training identity differs')
    model.load_state_dict(state['model'],strict=True);model.eval()
    return {'model':model,'request':request,'torch':torch,'pil_to_tensor':pil_to_tensor,
            'serving_runtime':serving_runtime,'serving_runtime_sha256':serving_runtime_sha,
            'detections':detections,'validate_sample':validate_sample,'validate_schema':validate_schema}


def predict(runtime,raw,sample):
    request=runtime['request'];contract=request['contract']
    runtime['validate_sample'](contract,sample)
    if not raw or len(raw)>20*1024*1024:raise ValueError('Image must be 1 byte to 20 MiB')
    from PIL import Image
    Image.MAX_IMAGE_PIXELS=40_000_000
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as source:
            if getattr(source,'n_frames',1)!=1:raise ValueError('Animated/video input requires another adapter')
            image=source.convert('RGB')
    with runtime['torch'].no_grad():prediction=runtime['model']([runtime['pil_to_tensor'](image).float()/255])[0]
    output={'detections':runtime['detections'](prediction['boxes'].tolist(),prediction['labels'].tolist(),prediction['scores'].tolist())}
    runtime['validate_schema'](contract['output_schema'],output)
    return {'sample_id':sample['sample_id'],'output':output,'device':'cpu','width':image.width,'height':image.height,
            'image_sha256':hashlib.sha256(raw).hexdigest(),'checkpoint_sha256':request['checkpoint_sha256'],
            'training_identity_hash':request['training_identity_hash'],
            'serving_runtime':runtime['serving_runtime'],'serving_runtime_sha256':runtime['serving_runtime_sha256']}


def infer(request):
    raw=base64.b64decode(request['image_base64'],validate=True)
    return predict(load_runtime(request),raw,request['sample'])


if __name__=='__main__':
    signal.alarm(60)  # Remote Linux CPU request; hard process deadline, no mutation.
    print(json.dumps(infer(json.load(sys.stdin))))
