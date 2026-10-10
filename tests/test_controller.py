import tempfile
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from vision_rsi.controller import parse_plan, research_step
from vision_rsi.ledger import Ledger


class ControllerTests(unittest.TestCase):
    @patch('vision_rsi.controller.execute',return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_snapshot_bounds_history_and_rejects_oversized_goal_before_admission(self,client,execute):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            for i in range(15):ledger.append('context-'+str(i),'evidence',{'summary':'s'*3000,'observation':'x'*8000})
            client.return_value.complete.return_value={'content':json.dumps({'tool':'inspect_repository','summary':'inspect','question':'q','expected_evidence':'e','refs':['goal']})}
            research_step({'llm':{'model':'fixture'},'remote':{}},folder)
            snapshot=next(e['payload']['request_snapshot'] for e in ledger.events() if e['payload'].get('record_type')=='planning_request')
            self.assertLessEqual(len(json.dumps(snapshot,sort_keys=True,ensure_ascii=False)),90000)
            prompt=json.loads(snapshot['messages'][0]['content'])
            self.assertGreater(prompt['history_projection']['omitted_oldest_count'],0)
            self.assertEqual(prompt['objective']['summary'],'goal')
        client.reset_mock()
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'x'*95000})
            with self.assertRaisesRegex(ValueError,'objective exceeds'):research_step({'llm':{'model':'fixture'},'remote':{}},folder)
            self.assertEqual(len(ledger.events()),1)
            client.return_value.complete.assert_not_called()

    @patch('vision_rsi.controller.execute',return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_request_snapshot_is_persisted_before_api_and_matches_sent_messages(self,client,execute):
        from vision_rsi.runner import digest
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            def complete(messages,max_tokens):
                request=ledger.events()[-1]['payload']
                self.assertEqual(request['record_type'],'planning_request')
                snapshot=request['request_snapshot']
                self.assertEqual(snapshot['messages'],messages)
                self.assertEqual(snapshot['max_tokens'],max_tokens)
                self.assertEqual(snapshot['thinking'],{'type':'disabled'})
                self.assertEqual(request['request_snapshot_sha256'],digest(snapshot))
                self.assertNotIn('api_key_env',snapshot)
                return {'content':json.dumps({'tool':'inspect_repository','summary':'inspect','question':'q','expected_evidence':'e','refs':['goal']})}
            client.return_value.complete.side_effect=complete
            research_step({'llm':{'model':'deepseek-flash','api_key_env':'KEY'},'remote':{}},folder)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_synthesis_preserves_findings_and_rejects_non_result_citations(self,client):
        from vision_rsi.controller import validate_synthesis_evidence,execute
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('inspect','action',{'executor':'research-v1','tool':'inspect_repository','summary':'inspect'})
            ledger.append('inspect:result','result',{'action':'inspect','status':'completed','summary':'observed',
                'observation':{'source_sha256':{'vision_rsi/controller.py':'a'*64}}})
            args={'findings':[{'statement':'Observed source identity is available.','refs':['inspect:result']}],
                  'limitations':['No training executed.'],'next_steps':['Read the observed source before designing an experiment.']}
            plan={'tool':'synthesize','arguments':args,'summary':'source findings','question':'q','expected_evidence':'e','refs':['inspect:result']}
            client.return_value.complete.return_value={'content':json.dumps(plan)}
            research_step({'llm':{'model':'fixture'},'remote':{}},folder)
            result=ledger.events()[-1]['payload']
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['observation']['findings'],args['findings'])
            self.assertTrue(result['observation']['interpretation_only'])
            self.assertFalse(result['observation']['experiment_executed'])
            for ref in ('goal','inspect',ledger.events()[-1]['key'],'missing'):
                invalid=dict(args,findings=[{'statement':'unsupported','refs':[ref]}])
                with self.assertRaises(ValueError):validate_synthesis_evidence(invalid,ledger.events())
            with self.assertRaises(ValueError):execute('synthesize',{},'.',None)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_synthesis_with_goal_citation_is_rejected_before_execution(self,client):
        with tempfile.TemporaryDirectory() as folder,patch('vision_rsi.controller.execute') as execute:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('inspect','action',{'executor':'research-v1','tool':'inspect_repository','summary':'inspect'})
            ledger.append('inspect:result','result',{'action':'inspect','status':'completed','summary':'observed','observation':{}})
            plan={'tool':'synthesize','summary':'bad','question':'q','expected_evidence':'e','refs':['goal'],
                  'arguments':{'findings':[{'statement':'claim','refs':['goal']}],'limitations':['none'],'next_steps':['train']}}
            client.return_value.complete.return_value={'content':json.dumps(plan)}
            research_step({'llm':{'model':'fixture'},'remote':{}},folder)
            execute.assert_not_called()
            self.assertEqual(ledger.events()[-1]['payload']['record_type'],'planning_rejected')

    def test_sorted_ledger_observation_projection_retains_source_hashes(self):
        from vision_rsi.controller import observation_context
        from vision_rsi.runner import digest
        original={'source_excerpts':{'README.md':'x'*100000},'source_sha256':{
            'vision_rsi/controller.py':'a'*64},'git_revision':'fixture'}
        # Ledger serializes keys in sorted order, putting excerpts ahead of hashes.
        reloaded=json.loads(json.dumps(original,sort_keys=True))
        result=observation_context(reloaded)
        self.assertEqual(result['source_sha256']['vision_rsi/controller.py'],'a'*64)
        self.assertEqual(result['observation_sha256'],digest(original))
        self.assertTrue(result['projection_truncated'])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),9000)
        many={'source_sha256':{'vision_rsi/source_'+str(i).zfill(3)+'.py':'b'*64 for i in range(128)},'source_excerpts':{}}
        result=observation_context(many)
        self.assertLessEqual(result['included_source_hash_count'],64)
        self.assertEqual(result['observed_source_hash_count'],128)

    @patch('vision_rsi.controller.execute',return_value={'fixture':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_model_selected_source_read_is_dispatched_after_repository_inspection(self,client,execute):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('inspect','action',{'executor':'research-v1','tool':'inspect_repository','summary':'inspect'})
            ledger.append('inspect:result','result',{'action':'inspect','status':'completed','summary':'observed',
                'observation':{'source_excerpts':{'README.md':'x'*50000},'source_sha256':{'vision_rsi/controller.py':'a'*64}}})
            args={'path':'vision_rsi/controller.py','start_line':1,'max_lines':20,'expected_sha256':'a'*64}
            plan={'tool':'read_source','arguments':args,'summary':'inspect detail','question':'q','expected_evidence':'e','refs':['inspect:result']}
            client.return_value.complete.return_value={'content':json.dumps(plan)}
            config={'llm':{'model':'fixture'},'remote':{}}
            research_step(config,folder)
            execute.assert_called_once_with('read_source',config,'.',args)
            prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
            self.assertIn('arguments',prompt['schema'])
            self.assertIn('REQUIRED',prompt['schema']['arguments_rule'])
            observed=next(row['observation'] for row in prompt['history'] if row['key']=='inspect:result')
            self.assertEqual(observed['source_sha256']['vision_rsi/controller.py'],'a'*64)
            self.assertEqual(ledger.events()[-1]['kind'],'result')
            research_step(config,folder)
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['payload']['record_type'],'planning_rejected')

    def test_source_read_is_hash_bound_and_rejects_unsafe_arguments(self):
        import hashlib
        from vision_rsi.controller import execute,source_arguments
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'vision_rsi').mkdir()
            path=root/'vision_rsi/example.py';path.write_bytes(b'first\nsecond\nthird\n')
            subprocess.run(['git','init'],cwd=root,capture_output=True,check=True)
            subprocess.run(['git','add','.'],cwd=root,capture_output=True,check=True)
            args={'path':'vision_rsi/example.py','start_line':2,'max_lines':1,'expected_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            result=execute('read_source',{},root,args)
            self.assertEqual(result['source_excerpt'],'second\n');self.assertEqual(result['end_line'],2)
            self.assertFalse(result['eof'])
            for key,value in [('path','../secret.py'),('max_lines',101),('start_line',True),('expected_sha256','bad')]:
                with self.assertRaises(ValueError):source_arguments(dict(args,**{key:value}))
            path.write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError,'changed since observation'):execute('read_source',{},root,args)

    @patch('vision_rsi.controller.execute',return_value={'fixture':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_known_not_dispatched_allows_explicit_new_request_without_resetting_limit(self,client,execute):
        from vision_rsi.llm import LLMNotDispatched
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            client.return_value.complete.side_effect=LLMNotDispatched('local fixture refusal')
            config={'llm':{'model':'fixture'},'remote':{}}
            for _ in range(6):
                with self.assertRaises(LLMNotDispatched):research_step(config,folder)
            events=ledger.events()
            requests=[e for e in events if e['payload'].get('record_type')=='planning_request']
            refused=[e for e in events if e['payload'].get('record_type')=='planning_not_dispatched']
            self.assertEqual(len(requests),6);self.assertEqual(len(refused),6)
            self.assertEqual({e['key'] for e in requests},{e['payload']['request_key'] for e in refused})
            research_step(config,folder)
            self.assertEqual(client.return_value.complete.call_count,6)
            execute.assert_not_called()

    @patch('vision_rsi.controller.execute',return_value={'fixture':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_explicit_retry_after_not_dispatched_can_complete(self,client,execute):
        from vision_rsi.llm import LLMNotDispatched
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            config={'llm':{'model':'fixture'},'remote':{}}
            client.return_value.complete.side_effect=LLMNotDispatched('fixture')
            with self.assertRaises(LLMNotDispatched):research_step(config,folder)
            client.return_value.complete.side_effect=None
            client.return_value.complete.return_value={'content':'{"tool":"inspect_repository","summary":"inspect","question":"q","expected_evidence":"e","refs":["goal"]}'}
            research_step(config,folder)
            self.assertEqual(client.return_value.complete.call_count,2)
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['kind'],'result')

    def test_repository_observation_hashes_dirty_source_without_reading_secrets(self):
        import hashlib
        from vision_rsi.controller import execute
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'vision_rsi').mkdir()
            source=root/'vision_rsi/example.py';source.write_bytes(b'print(1)\n')
            (root/'README.md').write_text('fixture')
            (root/'.env').write_text('MUST_NOT_READ')
            def git(*args):
                return subprocess.run(['git',*args],cwd=root,capture_output=True,check=True)
            git('init');git('add','.')
            git('-c','user.name=Fixture','-c','user.email=fixture@local.invalid','commit','-m','fixture')
            first=execute('inspect_repository',{},root)
            self.assertTrue(first['tracked_worktree_clean_before_and_after'])
            self.assertNotIn('.env',first['source_excerpts'])
            self.assertNotIn('MUST_NOT_READ',str(first))
            source.write_bytes(b'print(2)\n')
            second=execute('inspect_repository',{},root)
            self.assertEqual(first['git_revision'],second['git_revision'])
            self.assertFalse(second['tracked_worktree_clean_before_and_after'])
            self.assertEqual(second['source_sha256']['vision_rsi/example.py'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertNotEqual(first['source_sha256'],second['source_sha256'])
            source.write_bytes(b'x'*(1024*1024+1))
            third=execute('inspect_repository',{},root)
            self.assertNotIn('vision_rsi/example.py',third['source_excerpts'])
            self.assertTrue(any(row['reason']=='source_byte_limit' for row in third['skipped_sources']))
            for index in range(60):(root/'vision_rsi'/('source_'+str(index)+'.py')).write_text('x'*2500)
            git('add','.')
            bounded=execute('inspect_repository',{},root)
            self.assertLessEqual(len(json.dumps(bounded,sort_keys=True,ensure_ascii=False)),90000)
            self.assertGreater(bounded['source_excerpt_omitted_count'],0)
            ledger=Ledger(root/'observations')
            ledger.append('goal','objective',{'summary':'observation persistence fixture'})
            ledger.append('inspect','evidence',{'summary':'bounded repository','observation':bounded})

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_actual_process_death_releases_lock_and_recovers_pending_action(self,client):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('pending','action',{'executor':'research-v1','tool':'inspect_repository',
                                             'summary':'synthetic crash probe','refs':['goal']})
            program="""import os,sys
import vision_rsi.controller as controller
controller.execute=lambda *args:os._exit(73)
controller.research_step({'llm':{},'remote':{}},sys.argv[1])
"""
            child=subprocess.run([sys.executable,'-c',program,folder],
                                 cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=30)
            self.assertEqual(child.returncode,73,child.stderr)
            self.assertTrue((Path(folder)/'controller.lock').exists())
            self.assertFalse(any(e['kind']=='result' for e in ledger.events()))
            with patch('vision_rsi.controller.execute',return_value={'fixture':True}) as execute:
                research_step({'llm':{},'remote':{}},folder)
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['payload']['action'],'pending')
            client.assert_not_called()

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_active_os_lock_blocks_second_controller(self,client):
        from vision_rsi.campaign import lease
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            with lease(Path(folder)/'controller.lock'):
                with self.assertRaisesRegex(RuntimeError,'already active'):
                    research_step({'llm':{},'remote':{}},folder)
            self.assertEqual(len(ledger.events()),1)
            client.assert_not_called()

    def test_missing_key_does_not_leave_uncertain_planning_event(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'VISION_RSI_UNSET':''}), patch('vision_rsi.llm.urlopen') as http:
            ledger=Ledger(folder);ledger.append('goal','objective',{'summary':'goal'})
            config={'llm':{'model':'deepseek-flash','base_url':'https://example.invalid','api_key_env':'VISION_RSI_UNSET'},'remote':{}}
            with self.assertRaises(ValueError):research_step(config,folder)
            self.assertEqual(len(ledger.events()),1)
            http.assert_not_called()
    def test_no_arbitrary_tool_or_unknown_evidence(self):
        plan = {'tool':'shell','summary':'s','question':'q','expected_evidence':'e','refs':[]}
        import json
        with self.assertRaises(ValueError): parse_plan(json.dumps(plan), set())
        plan.update(tool='inspect_repository', refs=['missing'])
        with self.assertRaises(ValueError): parse_plan(json.dumps(plan), set())

    @patch('vision_rsi.controller.execute', return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_action_recovery_does_not_repeat_api(self, client, execute):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('request','evidence',{'summary':'request','record_type':'planning_request'})
            ledger.append('response','evidence',{'summary':'response','record_type':'planning_response',
                'request_key':'request','response':{'content':'{"tool":"inspect_repository","summary":"inspect","question":"q","expected_evidence":"e","refs":["goal"]}'}})
            result=research_step({'llm':{},'remote':{}},folder)
            client.assert_not_called()
            execute.assert_called_once()
            self.assertEqual(ledger.events()[-1]['kind'],'result')
            ledger.append('pause','paused',{'summary':'pause'})
            research_step({'llm':{},'remote':{}},folder)
            execute.assert_called_once()

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_uncertain_request_never_retries(self, client):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'goal'})
            ledger.append('request','evidence',{'summary':'request','record_type':'planning_request'})
            with self.assertRaises(RuntimeError):
                research_step({'llm':{},'remote':{}},folder)
            client.assert_not_called()
