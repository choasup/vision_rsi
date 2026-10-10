"""Local-file media transport for contract-bound remote inference."""
import base64
import json
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .contracts import validate_sample


def sample_request(contract,input_path):
    """Package one joint sample; video bytes retain the declared processing policy.

    This transport deliberately performs no decoding, frame sampling or inference.
    Relative media paths are resolved against the sample JSON file.
    """
    path=Path(input_path).resolve()
    if not path.is_file():raise ValueError('Sample JSON must be a local file')
    with path.open('rb') as stream:raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError('Sample JSON exceeds 1 MiB')
    sample=json.loads(raw.decode('utf-8-sig'))
    validate_sample(contract,sample)
    assets=[];total=0;policies={}
    for name,value in sample['inputs'].items():
        kind=value['type']
        if kind=='text':
            size=len(value['value'].encode('utf-8'))
            if size>256*1024:raise ValueError('Text input exceeds 256 KiB')
            total+=size
            continue
        items=value['items'] if kind=='image_list' else [value]
        if kind=='video':policies[name]=contract['inputs'][name]['processing']
        for index,item in enumerate(items):
            uri=item['uri']
            if uri.startswith('file:'):
                parts=urlsplit(uri)
                if parts.netloc not in ('','localhost') or parts.query or parts.fragment:raise ValueError('Only local file URIs supported')
                local=Path(url2pathname(parts.path))
            else:local=Path(uri)
            if not local.is_absolute():local=path.parent/local
            if not local.is_file():raise ValueError('Media must be a readable local file: '+str(local))
            limit=64*1024*1024 if kind=='video' else 20*1024*1024
            if len(assets)>=128:raise ValueError('Sample exceeds 128 media assets')
            remaining=64*1024*1024-total
            if remaining<=0:raise ValueError('Sample exceeds 64 MiB total content')
            with local.open('rb') as stream:content=stream.read(min(limit,remaining)+1)
            if not content or len(content)>limit:raise ValueError('Media is empty or exceeds per-file limit')
            total+=len(content)
            if total>64*1024*1024:raise ValueError('Sample exceeds 64 MiB total content')
            assets.append({'field':name,'index':index,'kind':'image' if kind=='image_list' else kind,
                           'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),
                           'content_base64':base64.b64encode(content).decode()})
    identity={'contract':contract,'sample':sample,'assets':[{k:v for k,v in asset.items() if k!='content_base64'} for asset in assets]}
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return {'protocol':'vision_sample_transport_v1','sample':sample,'assets':assets,'video_processing':policies,
            'input_fingerprint':fingerprint,'content_bytes':total,'media_decoded':False,'inference_performed':False}


def image_request(contract,input_path):
    path=Path(input_path).resolve()
    if len(contract['inputs'])!=1 or any(field['type']!='image' for field in contract['inputs'].values()):
        raise ValueError('This COCO inference adapter implements one image; joint images/video need their task adapter')
    name=next(iter(contract['inputs']))
    if path.suffix.lower()=='.json':
        raw_input=path.read_bytes()
        sample=json.loads(raw_input.decode('utf-8-sig'))
    else:
        sample={'sample_id':path.stem,'inputs':{name:{'type':'image','uri':str(path)}}}
        raw_input=json.dumps(sample,sort_keys=True).encode()
    validate_sample(contract,sample)
    uri=sample['inputs'][name]['uri']
    if uri.startswith('file:'):
        parts=urlsplit(uri)
        if parts.netloc not in ('','localhost') or parts.query or parts.fragment: raise ValueError('Only local file URIs supported')
        local=Path(url2pathname(parts.path))
    else:local=Path(uri)
    if not local.is_absolute():local=path.parent/local
    if not local.is_file():raise ValueError('Image is missing on the local machine: '+str(local))
    if not 0<local.stat().st_size<=20*1024*1024:raise ValueError('Image must be 1 byte to 20 MiB')
    content=local.read_bytes()
    if len(content)>20*1024*1024:raise ValueError('Image changed beyond size limit while reading')
    return {'sample':sample,'image_base64':base64.b64encode(content).decode(),
            'input_fingerprint':hashlib.sha256(raw_input+b'\0IMAGE\0'+content).hexdigest()}
