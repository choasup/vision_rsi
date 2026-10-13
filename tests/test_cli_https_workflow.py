import json,os,ssl,subprocess,threading,tempfile,shutil
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import unittest


class RealCLIWorkflowTests(unittest.TestCase):
    @unittest.skipUnless(os.name=="posix" and shutil.which("openssl"),"Requires POSIX launcher and openssl")
    def test_real_https_cli_generation_show_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem'),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            work=Path(tempfile.mkdtemp(prefix='workflow-',dir=root))
            original=Path(__file__).resolve().parents[1]
            repo=work/'source'
            subprocess.run(['git','clone','--quiet','--no-hardlinks',str(original),str(repo)],check=True)
            shutil.copytree(original/'vision_rsi',repo/'vision_rsi',dirs_exist_ok=True)
            shutil.copy2(original/'launch_agent.py',repo/'launch_agent.py')
            subprocess.run(['git','-C',str(repo),'add','vision_rsi','launch_agent.py'],check=True)
            subprocess.run(['git','-C',str(repo),'-c','user.name=Validation','-c','user.email=test@local.invalid','commit','--quiet','--allow-empty','-m','Isolated validation snapshot'],check=True)
            contract=json.loads((repo/'examples/interface-contract.json').read_text())
            contract.update(data_source={'kind':'public','location':'公开猫狗图片','download_allowed':True},budget=10)
            contract['acceptance'].update(mode='baseline',threshold=None)
            contract['open_questions']=[]
            source='\n'.join('def '+n+'(request):\n    raise ValueError("Real training resources not provided")\n' for n in ('load_data','train','predict','evaluate'))
            source+='\ndef smoke(request):\n    return {"stages":["load_data","train","predict","evaluate"],"training_performed":False}\n'
            proposal={'hypothesis':'Protocol only','expected_improvement':'No measured quality','evaluation_plan':'independent evaluation required','edits':[{'path':'vision_rsi/harness_validation.py','base_sha256':None,'content':source}]}
            requests=[]
            class Handler(BaseHTTPRequestHandler):
             def log_message(self,*a):pass
             def do_POST(self):
              payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
              system=payload['messages'][0]['content'];ctx=json.loads(payload['messages'][1]['content']);kind='clarify'
              if 'Infer the user' in system:
               kind='intent';msg=ctx['message']
               action={'往下做':'advance','查进度':'status','你自己搜索下载':'data','怎么还没运行':'explain','是':'accept'}.get(msg,'clarify')
               response={'action':action,'reason':'controlled test response','reply':'尚未启动真实训练。'}
              elif 'Generate one task-specific' in system:
               kind='generate';response=proposal
              else:response=contract
              requests.append(kind)
              content=json.dumps(response,ensure_ascii=False)
              if kind=='clarify' and any(t.get('content')=='TRUNCATED_FIXTURE' for t in ctx.get('turns',[])):content='```'
              if kind=='intent' and ctx['message']=='BROKEN_INTENT':content='[]'
              encoded=json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}).encode()
              self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'cert.pem',root/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            env=dict(os.environ,SSL_CERT_FILE=str(root/'cert.pem'),VISION_RSI_TEST_KEY='test-only-not-a-real-key',NO_PROXY='localhost,127.0.0.1',no_proxy='localhost,127.0.0.1')
            config={'llm':{'api_key_env':'VISION_RSI_TEST_KEY','base_url':'https://localhost:'+str(server.server_port),'model':'fixture'},'remote':{},'research':{}}
            (work/'config.local.json').write_text(json.dumps(config))
            def run(label,args,stdin=''):
             r=subprocess.run(['sh',str(repo/'vision-rsi.sh'),'training',*args,'--config',str(work/'config.local.json'),'--sessions',str(work/'sessions'),'--harness-root',str(work/'harness')],cwd=work,env=env,input=stdin,text=True,capture_output=True,timeout=60)
             (work/(label+'.log')).write_text(r.stdout+'\nSTDERR\n'+r.stderr)
             assert 'Traceback' not in r.stdout+r.stderr,(label,r.stdout,r.stderr)
             return r
            r=run('first',['start','--task-id','catdog','--interactive'],'猫狗分类，公开数据，先跑基线\n/show\n往下做\n查进度\n你自己搜索下载\n/quit\n')
            assert r.returncode==0 and requests==['clarify','intent','generate','intent','intent'],r.stdout+r.stderr
            assert '预算格式无效' in r.stdout
            assert '缺少远端配置' in r.stdout
            r=run('resume',['start','--task-id','catdog','--interactive'],'往下做\n/quit\n')
            assert r.returncode==0 and requests.count('generate')==1
            r=run('new',['start','--task-id','catdog','--new-session','--goal','second','--offline','--json'])
            assert r.returncode==0
            r=run('choose',['start','--task-id','catdog','--interactive'],'bad\n2\n/quit\n')
            assert r.returncode==0 and '选择无效' in r.stdout
            r=run('ambiguous',['start','--task-id','catdog','--json'])
            assert r.returncode==2 and json.loads(r.stdout)['status']=='selection_required'
            selected=json.loads(r.stdout)['sessions'][-1]['session_id']
            r=run('bad-intent',['show','--session-id',selected,'--interactive'],'BROKEN_INTENT\n/quit\n')
            assert r.returncode==0 and '未能可靠判断本次意图' in r.stdout
            assert requests.count('generate')==1
            r=run('truncated',['start','--task-id','truncated','--goal','TRUNCATED_FIXTURE','--json'])
            assert r.returncode==0,r.stderr
            result=json.loads(r.stdout)
            assert any('解析失败' in item for item in result['versions'][-1]['issues'])
            assert not result['pending_request']
