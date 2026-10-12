"""Loopback-only task console using the authoritative training session ledger."""
import argparse
import json
from pathlib import Path
import re
import secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from .contracts import Sessions
from .task_harness import configured_resources
from .training_cli import summary


def detail(store,session_id):
    session=store.show(session_id)
    contract=session['versions'][-1]['contract'] if session['versions'] else {}
    return {'session':session,'summary':summary(session),
            'resources':configured_resources(contract) if contract else None,
            'training_started':False,'scope':'Authoritative task requirements; execution control not yet connected to this console.'}


def make_server(root,config,port):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    sessions=Sessions(root/'sessions')
    sessions.list()  # Initialize schema before HTTP requests.
    token=secrets.token_urlsafe(32);host='127.0.0.1:'+str(port)
    page=Path(__file__).with_name('console.html').read_text(encoding='utf-8').replace('__TOKEN__',token)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,value,html=False):
            body=(value if html else json.dumps(value,ensure_ascii=False)).encode()
            self.send_response(status)
            self.send_header('Content-Type',('text/html' if html else 'application/json')+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
        def allowed(self):
            return self.headers.get('Host')==host and self.headers.get('X-Agent-Token')==token
        def do_GET(self):
            if self.headers.get('Host')!=host:return self.send(403,{'error':'Invalid host'})
            if self.path=='/':return self.send(200,page,True)
            if not self.allowed():return self.send(403,{'error':'Invalid token'})
            try:
                if self.path=='/api/tasks':return self.send(200,sessions.list())
                match=re.fullmatch('/api/tasks/([a-f0-9]{32})',self.path)
                if match:return self.send(200,detail(sessions,match[1]))
                if self.path=='/api/health':
                    from .credentials import read_key
                    key,_=read_key(config.get('llm',{}).get('api_key_env','DEEPSEEK_API_KEY'))
                    return self.send(200,{'status':'ready','storage':str(root),'execution_enabled':False,'llm_key_present':bool(key)})
                self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError,OSError) as error:self.send(400,{'error':str(error)})
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') not in (None,'http://'+host):return self.send(403,{'error':'Invalid request'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000:raise ValueError('Invalid body size')
                value=json.loads(self.rfile.read(size))
                if self.path=='/api/tasks':
                    # Save first, then clarify separately. No GPU or API side
                    # effects are hidden behind creating a task.
                    goal=value['goal'];task=value['task_id']
                    if not isinstance(goal,str) or not 1<=len(goal)<=4000:raise ValueError('Goal required, at most 4000 characters')
                    return self.send(200,sessions.create(task,goal))
                match=re.fullmatch('/api/tasks/([a-f0-9]{32})/(reply|budget)',self.path)
                if match:
                    session_id,action=match.groups()
                    if action=='budget':sessions.set_gpu_budget(session_id,value['gpu_hours'])
                    else:
                        message=value.get('message')
                        if not isinstance(message,str) or not 1<=len(message)<=4000:raise ValueError('Message required')
                        sessions.clarify(session_id,config['llm'],message)
                    return self.send(200,detail(sessions,session_id))
                self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError,OSError,RuntimeError) as error:self.send(400,{'error':str(error)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    host='127.0.0.1:'+str(server.server_address[1])
    server.agent_token=token
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--config',required=True)
    parser.add_argument('--port',type=int,default=8780)
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    from .campaign import lease
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=True)
    with lease(root/'console.lock',owner='Task console single writer'):
        server=make_server(root,config,args.port)
        print('Vision RSI task console: http://127.0.0.1:'+str(args.port),flush=True)
        try:server.serve_forever()
        finally:server.server_close()


if __name__=='__main__':main()
