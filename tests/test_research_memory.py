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

    def test_controller_retrieves_pages_once_without_remote_or_model(self):
        from vision_rsi.research_memory import memory_actions,retrieve_page,PAGE_CHARS
        from vision_rsi.campaign import available,execute,project
        from vision_rsi.strategy_context import history_context,encoded
        rows=self.state['history'];before=json.dumps(rows)
        state={'history':rows,'plan':{'status':'ready_to_submit'},'run_id':'fixture','run_status':'completed',
               'receipt_collected':True,'analysis':{'quality_verified':False},'research_rounds':1,'status':'needs_research'}
        self.assertEqual(available(state)[0]['kind'],'propose_experiment')
        action=next(a for a in available(state,memory=True) if a['kind']=='retrieve_memory')
        self.assertEqual(action['source_index'],10)
        page=execute(action,state,{}, {'remote':{}},None,None)
        self.assertLessEqual(len(page['text']),PAGE_CHARS);self.assertTrue(page['has_more'])
        self.assertEqual(json.dumps(rows),before)
        project(state,action,page);self.assertEqual(state['status'],'needs_research')
        rows.append({'action':action,'result':page,'status':'completed'})
        self.assertNotIn(action['id'],{a['id'] for a in memory_actions(rows)})
        self.assertEqual(memory_actions(rows)[0]['offset'],PAGE_CHARS)
        view=history_context(rows,4)
        projected=next(r for r in view if r['id']==action['id'])
        self.assertEqual(projected['observation']['memory_page'],page)
        self.assertLessEqual(len(encoded(view)),192*1024)
        rows[10]['result']['acceptance_review']['error_summary']['detail']='changed'
        with self.assertRaisesRegex(ValueError,'hash changed'):retrieve_page(rows,action)

    def test_all_pages_reconstruct_original_observation_and_exhaust(self):
        from vision_rsi.research_memory import memory_actions,retrieve_page
        from vision_rsi.strategy_context import encoded,history_context
        rows=self.state['history'];original=encoded(history_context(rows,3)[10]).decode('ascii');pieces=[]
        for _ in range(100):
            actions=memory_actions(rows)
            if not actions:break
            action=actions[0];page=retrieve_page(rows,action);pieces.append(page['text'])
            rows.append({'action':action,'result':page,'status':'completed'})
        else:self.fail('Retrieval did not terminate')
        self.assertEqual(''.join(pieces),original)
        self.assertNotIn('PRIVATE_MUST_NOT_EXPORT',''.join(pieces))

    def test_memory_cannot_read_arbitrary_records_or_unbounded_offsets(self):
        from vision_rsi.research_memory import memory_actions,retrieve_page
        rows=self.state['history'];action=memory_actions(rows)[0]
        for updates in ({'source_index':True},{'source_index':0},{'offset':-1},{'offset':1},{'offset':1000000},{'id':'invented'},{'source_sha256':'0'*64}):
            with self.assertRaises(ValueError):retrieve_page(rows,dict(action,**updates))
        self.assertEqual(memory_actions(rows[:5]),[])

    def test_advance_persists_memory_intent_and_page_without_training(self):
        from vision_rsi.campaign import advance
        from vision_rsi.runner import atomic_json
        session={'session_id':'session','task_id':'fixture','versions':[{'contract':{}}]}
        config={'remote':{'ssh_host':'fixture','workspace':'/workspace'}}
        root=self.root/'controller';runs=self.root/'runs'
        with patch('vision_rsi.campaign.prepare',return_value={'status':'blocked','blockers':['fixture']}):
            initial=advance(session,config,root,runs,steps=1,research_rounds=1)
        path=Path(initial['state_path']);state=json.loads(path.read_text(encoding='utf-8'))
        state.update(history=self.state['history'],plan={'status':'ready_to_submit'},run_id='fixture',run_status='completed',
                     receipt_collected=True,analysis={'quality_verified':False},status='needs_research')
        atomic_json(path,state)
        def choose_memory(state,actions,*args):
            action=next(a for a in actions if a['kind']=='retrieve_memory')
            return {'action_id':action['id'],'rationale':'Read omitted diagnosis before planning'},None
        with patch('vision_rsi.campaign.choose',side_effect=choose_memory),patch('vision_rsi.campaign.submit') as submit,patch('vision_rsi.experiments.propose_next') as propose:
            result=advance(session,config,root,runs,steps=1,research_rounds=1)
            submit.assert_not_called();propose.assert_not_called()
        self.assertIsNone(result['intent']);self.assertEqual(result['status'],'needs_research')
        row=result['history'][-1]
        self.assertEqual(row['action']['kind'],'retrieve_memory')
        self.assertEqual(row['controller_action_version'],2)
        self.assertEqual(row['tool_attempts'][0]['status'],'completed')
        self.assertEqual(row['result']['offset'],0)
