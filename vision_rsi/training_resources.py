"""Bounded local download of official COCO training images; no training or GPU use."""
import argparse
import json
from pathlib import Path
import shutil
import time

from .campaign import lease
from .resource_bootstrap import download


TRAIN_RESOURCE={'name':'train2017.zip',
                'url':'https://s3.amazonaws.com/images.cocodataset.org/zips/train2017.zip',
                'bytes':19336861798,'etag':'"62ff7d7fbcc7e0c0604cbb0f9047ce77-2306"'}


def step(root, seconds):
    if type(seconds) is not int or not 1<=seconds<=240:
        raise ValueError('Download window must be 1..240 seconds')
    root=Path(root).resolve()
    if root==Path(root.anchor):raise ValueError('Dedicated download directory required')
    root.mkdir(parents=True,exist_ok=True)
    with lease(root/'train-download.lock'):
        final=root/TRAIN_RESOURCE['name'];part=root/(TRAIN_RESOURCE['name']+'.part')
        existing=(final if final.exists() else part).stat().st_size if final.exists() or part.exists() else 0
        # Leave space for the remaining compressed archive and a full extraction.
        required=max(0,TRAIN_RESOURCE['bytes']-existing)+TRAIN_RESOURCE['bytes']+1024**3
        if shutil.disk_usage(root).free<required:
            raise ValueError('Insufficient disk for archive plus extraction reserve')
        try:
            result=download(TRAIN_RESOURCE,root,time.monotonic()+seconds)
        except TimeoutError:
            # A full archive can consume the remaining window before hashing
            # finishes. Retain it and report pending verification, never success.
            result={'status':'verification_pending','path':str(part),
                    'downloaded_bytes':part.stat().st_size if part.exists() else 0,
                    'asset':TRAIN_RESOURCE,'sha256_verified':False}
        return {'resource':result,'training_started':False,'gpu_used':False,
                'dataset_ready':False,'remaining_extraction_and_coverage_verification':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--seconds',type=int,default=240)
    args=parser.parse_args(argv)
    print(json.dumps(step(args.root,args.seconds),indent=2))


if __name__=='__main__':main()
