"""Private disposable HTTP worker; stdin may contain secrets, stdout never echoes them."""
import base64
import json
import os
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from vision_rsi.llm import MAX_RESPONSE_BYTES, _direct_open


def main():
    watchdog=None
    try:
        raw=sys.stdin.buffer.read(20*1024*1024+1)
        if len(raw)>20*1024*1024:raise ValueError('Input limit')
        value=json.loads(raw)
        watchdog=threading.Timer(value['timeout'],os._exit,args=(124,))
        watchdog.daemon=True
        watchdog.start()
        data=None if value['data'] is None else base64.b64decode(value['data'],validate=True)
        request=Request(value['url'],data=data,headers=value['headers'])
        with _direct_open(request,value['timeout']) as response:
            body=response.read(MAX_RESPONSE_BYTES+1)
        result=b'OVERSIZED\n' if len(body)>MAX_RESPONSE_BYTES else b'OK\n'+body
    except HTTPError as error:
        result=b'HTTP '+str(error.code).encode()+b'\n'
        error.close()
    except BaseException:
        result=b'ERROR\n'
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()
    if watchdog is not None:watchdog.cancel()


if __name__=='__main__':main()
