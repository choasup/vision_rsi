"""CPU-only full image decode and fingerprinting; this does not measure model AP."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import warnings

from .detector import split_check


def verify_images(root, split, expected_images):
    from PIL import Image, ImageFile
    root=Path(root)
    checked=split_check(root,split,expected_images)
    if not checked['ready']:
        raise ValueError(checked['reason'])
    annotation=root/'annotations'/f'instances_{split}2017.json'
    raw=annotation.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=checked['annotation_sha256']:
        raise ValueError('Annotations changed during verification')
    data=json.loads(raw); fingerprint=hashlib.sha256();total=0
    Image.MAX_IMAGE_PIXELS=40_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES=False
    for item in sorted(data['images'],key=lambda row:row['id']):
        path=root/f'{split}2017'/item['file_name']
        if not 0<path.stat().st_size<=20*1024*1024:
            raise ValueError('Image exceeds byte limit')
        content=path.read_bytes()
        if len(content)>20*1024*1024:raise ValueError('Image grew beyond byte limit')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format!='JPEG' or image.size!=(item['width'],item['height']):
                    raise ValueError('Unexpected image format/dimensions')
                image.load()
        image_sha=hashlib.sha256(content).hexdigest()
        fingerprint.update(json.dumps([item['id'],item['file_name'],image_sha],separators=(',',':')).encode()+b'\n')
        total+=len(content)
    if hashlib.sha256(annotation.read_bytes()).hexdigest()!=checked['annotation_sha256']:
        raise ValueError('Annotations changed during verification')
    return {'split':split,'images':expected_images,'annotations':checked['annotations'],
            'zero_area_annotation_ids':checked['zero_area_annotation_ids'],
            'training_box_policy':checked['training_box_policy'],
            'annotation_sha256':checked['annotation_sha256'],'image_manifest_sha256':fingerprint.hexdigest(),
            'image_bytes':total,'pixel_decode_verified':True,'coco_evaluated':False,
            'training_started':False,'gpu_used':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    print(json.dumps(verify_images(args.root,'val',5000),indent=2))
