"""Local-file media transport for contract-bound remote inference."""
import base64
import json
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .contracts import validate_sample


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
