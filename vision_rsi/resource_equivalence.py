"""Rehash a full split against a pinned, fully decoded reference receipt."""
import argparse
import hashlib
import json
from pathlib import Path

from .detector import split_check


def hex_sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def verify(root,reference_path,reference_sha256,progress=None):
    if not hex_sha(reference_sha256):raise ValueError('Pinned reference receipt SHA-256 required')
    with Path(reference_path).open('rb') as stream:raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=reference_sha256:
        raise ValueError('Reference receipt size or SHA-256 differs')
    reference=json.loads(raw)
    split=reference.get('split');count=reference.get('images')
    if (split not in ('train','val') or type(count) is not int
            or count!=(118287 if split=='train' else 5000)
            or reference.get('pixel_decode_verified') is not True
            or reference.get('gpu_used') is not False or reference.get('training_started') is not False
            or reference.get('coco_evaluated') is not False
            or type(reference.get('image_bytes')) is not int or reference['image_bytes']<=0
            or not hex_sha(reference.get('annotation_sha256'))
            or not hex_sha(reference.get('image_manifest_sha256'))):
        raise ValueError('Reference must prove full-split CPU pixel verification, not partial or model quality')
    root=Path(root)
    if progress:progress({'status':'checking_coverage','hashed_images':0,'total_images':count,'byte_equivalence_verified':False})
    checked=split_check(root,split,count)
    if not checked['ready']:raise ValueError(checked['reason'])
    if (checked['annotation_sha256']!=reference['annotation_sha256']
            or checked['annotations']!=reference.get('annotations')
            or checked['zero_area_annotation_ids']!=reference.get('zero_area_annotation_ids',[])):
        raise ValueError('Reference annotations differ from target split')
    annotation=root/'annotations'/f'instances_{split}2017.json'
    raw=annotation.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference['annotation_sha256']:
        raise ValueError('Annotations changed during equivalence check')
    images=sorted(json.loads(raw)['images'],key=lambda image:image['id'])
    fingerprint=hashlib.sha256();total=0
    for number,image in enumerate(images,1):
        path=root/f'{split}2017'/image['file_name'];size=path.stat().st_size
        if not 0<size<=20*1024*1024:raise ValueError('Image exceeds byte limit')
        checksum=hashlib.sha256();read=0
        with path.open('rb') as stream:
            while block:=stream.read(1024*1024):
                read+=len(block)
                if read>20*1024*1024:raise ValueError('Image grew beyond byte limit')
                checksum.update(block)
        if read!=size:raise ValueError('Image changed during equivalence check')
        fingerprint.update(json.dumps([image['id'],image['file_name'],checksum.hexdigest()],separators=(',',':')).encode()+b'\n')
        total+=read
        if progress and number%1000==0:
            progress({'status':'hashing_images','hashed_images':number,'total_images':count,'byte_equivalence_verified':False})
    if hashlib.sha256(annotation.read_bytes()).hexdigest()!=reference['annotation_sha256']:
        raise ValueError('Annotations changed during equivalence check')
    if fingerprint.hexdigest()!=reference['image_manifest_sha256'] or total!=reference['image_bytes']:
        raise ValueError('Full image bytes differ from decoded reference')
    result={'split':split,'images':count,'annotations':checked['annotations'],
            'reference_receipt_sha256':reference_sha256,'annotation_sha256':reference['annotation_sha256'],
            'image_manifest_sha256':fingerprint.hexdigest(),'image_bytes':total,
            'byte_equivalence_verified':True,'reference_pixel_decode_verified':True,
            'pixel_decode_verified':False,'coco_evaluated':False,'training_started':False,'gpu_used':False,
            'dataset_ready':False}
    if progress:progress(dict(result,status='completed',hashed_images=count,total_images=count))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--reference',required=True)
    parser.add_argument('--reference-sha256',required=True)
    args=parser.parse_args(argv)
    try:result=verify(args.root,args.reference,args.reference_sha256)
    except (ValueError,TypeError,KeyError,OSError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
