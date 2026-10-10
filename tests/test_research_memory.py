import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from vision_rsi.research_memory import read_memory
from vision_rsi.runner import digest
from vision_rsi.training_cli import main


class ResearchMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        binding={'session_id':'session','contract':{}}
        self.cid=digest(binding);self.path=self.root/'campaigns/session'/self.cid/'state.json';self.path.parent.mkdir(parents=True)
        rows=[{'action':{'id':'observe-'+str(i),'kind':'observe'},'status':'completed',
               'result':{'run_id':'fixture','status':'running','reserved_gpu_hours':.5,'api_key':'PRIVATE_MUST_NOT_EXPORT'}} for i in range(1000)]
        rows[10]={'action':{'id':'analyze-10','kind':'analyze'},'status':'completed','result':{
                  'metric_gap':20,'acceptance_review':{'box_AP':40,'threshold':60,'error_summary':{'detail':'x'*20000}}}}
        self.state={'campaign_id':self.cid,'binding':binding,'history':rows};self.save()
    def save(self):self.path.write_text(json.dumps(self.state),encoding='utf-8')
    def read(self,**kwargs):return read_memory('session',self.cid,self.root/'campaigns',**kwargs)

    def test_original_detail_is_hash_bound_and_can_be_read_after_append(self):
        before=self.path.read_bytes();view=self.read();checksum=view['context_sha256']
        self.assertEqual(view['view'][0]['observation']['full_context_sha256'],checksum)
        self.assertTrue(view['read_only']);self.assertFalse(view['remote_polled'])
        self.assertNotIn('PRIVATE_MUST_NOT_EXPORT',str(view))
        detail=self.read(source_index=10,context_sha256=checksum)
        self.assertEqual(len(detail['original_observation']['observation']['error_summary']['detail']),20000)
        self.assertEqual(self.path.read_bytes(),before)
        self.state['history'].append({'action':{'id':'observe-1000','kind':'observe'},'status':'completed','result':{}});self.save()
        self.assertEqual(detail['original_observation'],self.read(source_index=10,context_sha256=checksum,history_rows=1000)['original_observation'])
        with self.assertRaisesRegex(ValueError,'hash changed'):self.read(source_index=10,context_sha256=checksum)
        self.state['history'][0]['result']['reserved_gpu_hours']=.6;self.save()
        with self.assertRaisesRegex(ValueError,'hash changed'):self.read(source_index=10,context_sha256=checksum,history_rows=1000)

    def test_invalid_reference_never_returns_detail_or_creates_missing_store(self):
        with self.assertRaisesRegex(ValueError,'exact --context'):self.read(source_index=10)
        for index in (-1,1000,True):
            with self.assertRaisesRegex(ValueError,'outside snapshot'):self.read(source_index=index,context_sha256=self.read()['context_sha256'])
        with self.assertRaises(FileNotFoundError):read_memory('missing',self.cid,self.root/'absent')
        self.assertFalse((self.root/'absent').exists())

    def test_cli_memory_is_read_only_and_does_not_open_sessions(self):
        before=self.path.read_bytes();sessions=self.root/'must-not-create';out=io.StringIO()
        with patch('vision_rsi.training_cli.Sessions') as store,redirect_stdout(out):
            main(['memory','--session-id','session','--campaign-id',self.cid,'--campaign-store',str(self.root/'campaigns'),'--sessions',str(sessions),'--json'])
            store.assert_not_called()
        self.assertTrue(json.loads(out.getvalue())['read_only'])
        self.assertFalse(sessions.exists());self.assertEqual(self.path.read_bytes(),before)

    def test_module_entrypoint_routes_memory_without_mutating_state(self):
        before=self.path.read_bytes()
        command=[sys.executable,'-X','utf8','-m','vision_rsi','training','memory',
                 '--session-id','session','--campaign-id',self.cid,
                 '--campaign-store',str(self.root/'campaigns'),'--json']
        completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertTrue(json.loads(completed.stdout)['read_only'])
        self.assertEqual(self.path.read_bytes(),before)
