"""Loopback-only task console using the authoritative training session ledger."""
import argparse
import json
from pathlib import Path
import re
import secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from .contracts import Sessions
from .task_harness import configured_resources
from .training_cli import conversation_summary as summary


def capabilities(config):
    import importlib.util
    import sys
    from .credentials import read_key
    llm = config.get('llm', {})
    key, _ = read_key(llm.get('api_key_env', 'DEEPSEEK_API_KEY'))
    model_ready = bool(key and llm.get('model') and llm.get('base_url'))
    cpu = importlib.util.find_spec('sklearn') is not None
    return {'cpu_demo_ready': cpu, 'model_configured': model_ready,
            'general_training_ready': False,
            'checks': [
                {'ready': cpu, 'message': 'CPU 示例实验可运行，无需模型凭据。' if cpu else 'CPU 示例缺少依赖，请先运行：'+sys.executable+' -m pip install "scikit-learn==1.8.0"（Python 3.11+）。'},
                {'ready': model_ready, 'message': '模型配置与凭据已找到；实际连通性将在请求时验证。' if model_ready else '任务对话暂不可用：请在配置中设置模型，并在启动环境中设置 '+llm.get('api_key_env','DEEPSEEK_API_KEY')+'。CPU 示例不需要它。'},
                {'ready': False, 'message': '猫狗等通用训练尚未接通；可保存需求。候选后端构建在高级详情中提供。'}]}


def local_host(value):
    # Permit localhost and alternate forwarded ports, never arbitrary Host names.
    match = re.fullmatch(r'(127\.0\.0\.1|localhost)(?::([0-9]{1,5}))?', value or '')
    return bool(match and (match[2] is None or 1 <= int(match[2]) <= 65535))


def experiment_readiness(session):
    """Report actual console execution limits; no API calls or task rewriting."""
    from .task_adapters import training_adapter
    latest = session['versions'][-1] if session.get('versions') else {}
    contract = latest.get('contract') or {}
    adapter = training_adapter(contract)
    blockers = []
    if not contract:
        blockers.append('需求已保存，尚未形成可执行的任务定义。')
    if latest.get('review_required'):
        blockers.append('需求变更尚未确认。')
    if session.get('pending_request'):
        blockers.append('有未完成的需求请求，请先核对原请求结果。')
    if not adapter['implementation_supported']:
        blockers.append('此任务与现有 COCO 检测训练适配器不兼容，尚无可直接启动的训练后端。')
    else:
        blockers.append('任务接口兼容 COCO，但工作台尚未接入该适配器的训练提交；需通过 Training CLI 检查配置和运行。')
    source = contract.get('data_source')
    if isinstance(source, dict) and source.get('kind') == 'public':
        blockers.append('公开数据搜索和下载尚未接通，当前没有已校验的数据可供此入口训练。')
    return {'can_start': False, 'status': 'blocked', 'training_started': False,
            'blockers': blockers, 'adapter': adapter,
            'next_step': '需求会保留。候选构建仅生成和检查代码，不等于启动训练；CPU 示例是另一个独立实验。'}


def detail(store,session_id):
    session=store.show(session_id)
    contract=session['versions'][-1]['contract'] if session['versions'] else {}
    return {'session':session,'summary':summary(session),'experiment':experiment_readiness(session),
            'resources':configured_resources(contract) if contract else None,
            'training_started':False,'scope':'任务需求与 CLI 共用；候选构建可推进，通用训练尚未接通。'}


def make_server(root,config,port,*,sessions_root=None,harness_root=None,repository=None):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    sessions=Sessions(sessions_root or root/'sessions')
    from .console_jobs import Jobs, ARTIFACTS
    jobs=Jobs(root,sessions.root,harness_root or root/'harnesses',repository or Path(__file__).resolve().parent.parent,config)
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
            return local_host(self.headers.get('Host')) and self.headers.get('X-Agent-Token')==token
        def do_GET(self):
            if not local_host(self.headers.get('Host')):return self.send(403,{'error':'请使用 localhost 或 127.0.0.1，通过本地访问或 SSH 端口转发连接。'})
            if self.path=='/':return self.send(200,page,True)
            if self.path=='/health':return self.send(200,{'application':'vision-rsi-dashboard','status':'ready'})
            if not self.allowed():return self.send(403,{'error':'Invalid token'})
            try:
                if self.path=='/api/tasks':return self.send(200,sessions.list())
                match=re.fullmatch('/api/tasks/([a-f0-9]{32})',self.path)
                if match:
                    result=detail(sessions,match[1])
                    from .harness_progress import status
                    try:result['progress']=status(result['session'],jobs.harness_root)
                    except (ValueError,KeyError,TypeError,OSError) as error:result['progress']={'status':'requirements_pending','next_step':str(error)}
                    result['jobs']=[job for job in jobs.list() if job['task_id']==result['session']['task_id']]
                    return self.send(200,result)
                if self.path=='/api/jobs':return self.send(200,jobs.list())
                match=re.fullmatch('/api/jobs/([a-f0-9]{32})',self.path)
                if match:return self.send(200,jobs.show(match[1]))
                match=re.fullmatch('/api/jobs/([a-f0-9]{32})/artifacts/([a-z.-]+)',self.path)
                if match:
                    job_id,name=match.groups()
                    if name not in ARTIFACTS:raise ValueError('Unknown artifact')
                    return self.send(200,json.loads((jobs.folder(job_id)/'experiment'/name).read_text()))
                if self.path=='/api/health':
                    from .credentials import read_key
                    key,_=read_key(config.get('llm',{}).get('api_key_env','DEEPSEEK_API_KEY'))
                    return self.send(200,{'status':'ready','storage':str(root),'execution_enabled':True,'general_training_enabled':False,'llm_key_present':bool(key),'capabilities':capabilities(config)})
                self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError,OSError) as error:self.send(400,{'error':str(error)})
        def do_HEAD(self):
            if not local_host(self.headers.get('Host')):
                self.send_response(403)
            else:
                self.send_response(200 if self.path in ('/','/health') else 404)
            self.end_headers()
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')):return self.send(403,{'error':'Invalid request'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000:raise ValueError('Invalid body size')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('Body must be an object')
                if self.path=='/api/tasks':
                    # Save first, then clarify separately. No GPU or API side
                    # effects are hidden behind creating a task.
                    goal=value['goal'];task=value.get('task_id') or ('task-'+__import__('uuid').uuid4().hex[:12])
                    if not isinstance(goal,str) or not 1<=len(goal)<=4000:raise ValueError('Goal required, at most 4000 characters')
                    opening=sessions.start(task,goal)
                    if opening['status']=='selection_required':return self.send(409,{'error':'该任务已有多个会话，请从左侧任务列表选择。'})
                    return self.send(200,opening['session'])
                if self.path=='/api/demo':
                    if not capabilities(config)['cpu_demo_ready']:return self.send(409,{'error':capabilities(config)['checks'][0]['message']})
                    return self.send(202,jobs.start('cpu-demo'))
                match=re.fullmatch('/api/jobs/([a-f0-9]{32})/stop',self.path)
                if match:return self.send(200,jobs.stop(match[1]))
                match=re.fullmatch('/api/tasks/([a-f0-9]{32})/(reply|start|advance|accept|reject|budget)',self.path)
                if match:
                    session_id,action=match.groups()
                    session=sessions.show(session_id)
                    if action=='start':
                        readiness=experiment_readiness(session)
                        return self.send(409,{'error':'实验未启动：'+'；'.join(readiness['blockers']), 'experiment':readiness})
                    if action in ('advance','accept','reject'):
                        return self.send(202,jobs.start(action,session,version=value.get('version')))
                    if action=='budget':
                        with jobs.lock:
                            if any(j['task_id']==session['task_id'] and j['status'] in ('queued','running','stopping') for j in jobs.list()):
                                raise ValueError('请等待当前操作结束再修改预算。')
                            sessions.set_gpu_budget(session_id,value['gpu_hours'])
                    else:
                        message=value.get('message')
                        if not isinstance(message,str) or not 1<=len(message)<=4000:raise ValueError('Message required')
                        return self.send(202,jobs.start('reply',session,message))
                    return self.send(200,detail(sessions,session_id))
                self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError,OSError,RuntimeError) as error:self.send(400,{'error':str(error)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    host='127.0.0.1:'+str(server.server_address[1])
    server.agent_token=token
    server.jobs=jobs
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--config',required=True)
    parser.add_argument('--port',type=int,default=8780)
    parser.add_argument('--sessions',help='Existing CLI training-sessions directory')
    parser.add_argument('--harness-root',help='Existing CLI task-harnesses directory')
    parser.add_argument('--repository',default=str(Path(__file__).resolve().parent.parent))
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    from .campaign import lease
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=True)
    with lease(root/'console.lock',owner='Task console single writer'):
        server=make_server(root,config,args.port,sessions_root=args.sessions,harness_root=args.harness_root,repository=args.repository)
        print('Vision RSI task console: http://127.0.0.1:'+str(args.port),flush=True)
        try:server.serve_forever()
        finally:server.server_close()


if __name__=='__main__':main()
