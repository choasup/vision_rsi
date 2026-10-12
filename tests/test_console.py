import json
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from vision_rsi.console import make_server


class ConsoleTests(unittest.TestCase):
    def test_task_creation_observation_and_request_boundaries(self):
        with tempfile.TemporaryDirectory() as root:
            server=make_server(root,{'llm':{}},0)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            address='http://127.0.0.1:'+str(server.server_address[1])
            def request(path,data=None,token=True):
                headers={'Content-Type':'application/json'}
                if token:headers['X-Agent-Token']=server.agent_token
                with urlopen(Request(address+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=5) as response:
                    return json.load(response)
            with self.assertRaises(HTTPError):request('/api/tasks',token=False)
            created=request('/api/tasks',{'task_id':'catdog','goal':'猫狗分类'})
            detail=request('/api/tasks/'+created['session_id'])
            self.assertEqual(detail['session']['task_id'],'catdog')
            self.assertFalse(detail['training_started'])
            self.assertEqual(len(request('/api/tasks')),1)
            self.assertFalse(request('/api/health')['execution_enabled'])
