"""CPU-only full image decode and fingerprinting; this does not measure model AP."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import warnings

from .detector import split_check


def verify_images(root, split, expected_images, progress=None):
    from PIL import Image, ImageFile
    root=Path(root)
    def report(status,count):
        if progress is not None:
            progress({'status':status,'split':split,'decoded_images':count,'total_images':expected_images,
                      'verification_complete':status=='completed','dataset_ready':False,
                      'training_started':False,'gpu_used':False})
    report('checking_coverage',0)
    checked=split_check(root,split,expected_images)
    if not checked['ready']:
        raise ValueError(checked['reason'])
    annotation=root/'annotations'/f'instances_{split}2017.json'
    raw=annotation.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=checked['annotation_sha256']:
        raise ValueError('Annotations changed during verification')
    data=json.loads(raw); fingerprint=hashlib.sha256();total=0;formats={}
    Image.MAX_IMAGE_PIXELS=40_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES=False
    report('decoding_images',0)
    for count,item in enumerate(sorted(data['images'],key=lambda row:row['id']),1):
        path=root/f'{split}2017'/item['file_name']
        if not 0<path.stat().st_size<=20*1024*1024:
            raise ValueError('Image exceeds byte limit')
        content=path.read_bytes()
        if len(content)>20*1024*1024:raise ValueError('Image grew beyond byte limit')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ('JPEG','PNG') or image.size!=(item['width'],item['height']) or getattr(image,'n_frames',1)!=1:
                    raise ValueError(f"Unexpected image format/dimensions: image {item['id']} {item['file_name']}, {image.format} {image.size}")
                image.load()
                formats[image.format]=formats.get(image.format,0)+1
        image_sha=hashlib.sha256(content).hexdigest()
        fingerprint.update(json.dumps([item['id'],item['file_name'],image_sha],separators=(',',':')).encode()+b'\n')
        total+=len(content)
        if count%1000==0:report('decoding_images',count)
    if hashlib.sha256(annotation.read_bytes()).hexdigest()!=checked['annotation_sha256']:
        raise ValueError('Annotations changed during verification')
    report('completed',expected_images)
    return {'split':split,'images':expected_images,'annotations':checked['annotations'],
            'formats':formats,
            'zero_area_annotation_ids':checked['zero_area_annotation_ids'],
            'training_box_policy':checked['training_box_policy'],
            'annotation_sha256':checked['annotation_sha256'],'image_manifest_sha256':fingerprint.hexdigest(),
            'image_bytes':total,'pixel_decode_verified':True,'coco_evaluated':False,
            'training_started':False,'gpu_used':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--split',choices=('train','val'),default='val')
    parser.add_argument('--progress',help='New JSON sidecar outside the dataset; progress is not a resume receipt')
    args=parser.parse_args()
    callback=None
    if args.progress:
        from .runner import atomic_json
        original=Path(args.progress);sidecar=original.resolve()
        if original.is_symlink() or sidecar.exists() or sidecar.is_relative_to(Path(args.root).resolve()):
            parser.error('Progress path must be new and outside the dataset')
        callback=lambda value:atomic_json(sidecar,value)
    print(json.dumps(verify_images(args.root,args.split,118287 if args.split=='train' else 5000,callback),indent=2))
