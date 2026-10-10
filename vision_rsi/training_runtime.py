"""Runtime identity for new GPU experiments; no GPU work at module import."""
import hashlib
import importlib.metadata
import os
import platform
import re
import subprocess


def fingerprint(torch,device):
    """Bind environment evidence, excluding transient utilization/device indices.

    Called inside an admitted GPU training job. This is a resume guard, not
    a proof of numerical equivalence or a portable dependency installation lock.
    """
    versions={name:importlib.metadata.version(name)
              for name in ('torch','torchvision','pycocotools','Pillow','numpy')}
    result=subprocess.run(['nvidia-smi','--query-gpu=driver_version','--format=csv,noheader'],
                          capture_output=True,text=True,timeout=10,check=True)
    drivers=result.stdout.strip().splitlines()
    if not drivers or any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+',line.strip()) for line in drivers):
        raise ValueError('Unable to verify CUDA driver version for checkpoint identity')
    props=torch.cuda.get_device_properties(device)
    nccl=torch.cuda.nccl.version()
    cudnn=torch.backends.cudnn.version()
    cuda=torch.version.cuda
    if (not isinstance(cuda,str) or not cuda or type(cudnn) is not int or cudnn<=0
            or not isinstance(nccl,tuple) or len(nccl) not in (3,4)
            or any(type(n) is not int or n<0 for n in nccl[:3])
            or (len(nccl)==4 and (not isinstance(nccl[3],str) or not nccl[3]))):
        raise ValueError('Incomplete CUDA/cuDNN/NCCL runtime identity')
    return {'schema':'vision-rsi-training-runtime-v1','python':platform.python_version(),
            'platform':platform.platform(),'packages':versions,'cuda_build':cuda,'cudnn':cudnn,'nccl':list(nccl),
            'driver_versions':sorted(set(line.strip() for line in drivers)),
            'torch_build_sha256':hashlib.sha256(torch.__config__.show().encode()).hexdigest(),
            'device':{'name':props.name,'compute_capability':[props.major,props.minor],'total_memory':props.total_memory},
            'determinism':{'algorithms':torch.are_deterministic_algorithms_enabled(),
                           'cudnn_benchmark':torch.backends.cudnn.benchmark,
                           'cudnn_deterministic':torch.backends.cudnn.deterministic,
                           'matmul_tf32':torch.backends.cuda.matmul.allow_tf32,
                           'cudnn_tf32':torch.backends.cudnn.allow_tf32,
                           'cublas_workspace':os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
                           'compile_disabled':os.environ.get('TORCH_COMPILE_DISABLE')}}
