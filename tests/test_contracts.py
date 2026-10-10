import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from vision_rsi.contracts import Sessions,issues,validate_sample,validate_schema,validate_manifest

class ContractTests(unittest.TestCase):
    def test_event_protocol_requires_executable_acceptance_fields(self):
        from vision_rsi.event_eval import PROTOCOL
        contract=json.loads(json.dumps(self.contract))
        contract['acceptance']={'metric':'event_micro_f1','direction':'maximize',
                                'evaluation_protocol':PROTOCOL,'threshold':.9,'iou_threshold':.5}
        contract['output_schema']={'type':'object','properties':{'events':{'type':'array','items':{'type':'object','properties':{}}}}}
        contract['example_output']={'events':[]}
        self.assertEqual(issues(contract),[])
        for key,value,fragment in [('iou_threshold',None,'iou_threshold'),('iou_threshold',True,'iou_threshold'),
                                   ('threshold',90,'0..1'),('metric','AP','event_micro_f1'),
                                   ('direction','minimize','event_micro_f1')]:
            changed=json.loads(json.dumps(contract));changed['acceptance'][key]=value
            self.assertTrue(any(fragment in error for error in issues(changed)))
        contract['output_schema']={'type':'object','properties':{'other':{'type':'string'}}}
        self.assertTrue(any('events' in error for error in issues(contract)))
        contract['output_schema']={'type':'object','properties':42}
        self.assertTrue(any('events' in error for error in issues(contract)))

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_clarification_describes_event_evaluator_without_claiming_video_training(self,client):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root);session=store.create('video-task','Find events in a video')['session_id']
            client.return_value.complete.return_value={'content':json.dumps(self.contract)}
            store.clarify(session,{'model':'fixture'},'F1 at least 0.9')
            prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
            defaults=prompt['available_evaluation_defaults']['video_events']
            self.assertEqual(defaults['metric_scale'],'0..1')
            self.assertIn('no video model training',defaults['implementation_scope'])
            self.assertIn('Never replace an explicit metric',defaults['selection_policy'])

    def setUp(self): self.contract=json.loads(Path('examples/interface-contract.json').read_text())
    def test_missing_key_does_not_leave_pending_clarification(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ',{'VISION_RSI_UNSET':''}), patch('vision_rsi.llm.urlopen') as http:
            store=Sessions(root);session=store.create('inspection','goal')['session_id']
            config={'model':'deepseek-flash','base_url':'https://example.invalid','api_key_env':'VISION_RSI_UNSET'}
            with self.assertRaises(ValueError):store.clarify(session,config,'additional requirement')
            self.assertFalse(store.show(session)['pending_request'])
            with store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM clarification_requests').fetchone()[0],0)
            http.assert_not_called()
    def test_joint_video_and_output_contract(self):
        self.assertEqual(issues(self.contract),[])
        self.assertTrue(validate_sample(self.contract,self.contract['example_input'])['valid'])
        self.contract['example_input']['inputs']['views']['items'].pop()
        self.assertTrue(issues(self.contract))
        with self.assertRaises(ValueError):validate_schema(self.contract['output_schema'],{'defects':[{'label':'scratch','start_seconds':-1}]})
    def test_persistent_versions_and_missing_policy(self):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root);session=store.create('inspection','goal')['session_id']
            self.assertEqual(store.define(session,self.contract)['status'],'ready_for_harness')
            self.contract['inputs']['clip']['processing'].pop('temporal')
            updated=Sessions(root).define(session,self.contract)
            self.assertEqual(updated['status'],'clarifying')
            self.assertEqual(len(updated['versions']),2)
            self.assertEqual(updated['turns'][0]['content'],'goal')
    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_clarification_and_uncertain_call(self,client):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root);session=store.create('inspection','goal')['session_id']
            client.return_value.complete.return_value={'content':json.dumps(self.contract),'usage':{'total_tokens':10}}
            result=store.clarify(session,{'model':'fixture'},'Use joint images')
            self.assertEqual(result['status'],'ready_for_harness')
            self.assertEqual(result['turns'][1]['content'],'Use joint images')
            client.return_value.complete.side_effect=RuntimeError('timeout')
            with self.assertRaises(RuntimeError):store.clarify(session,{'model':'fixture'},'change')
            before=client.return_value.complete.call_count
            with self.assertRaises(RuntimeError):store.clarify(session,{'model':'fixture'})
            self.assertEqual(client.return_value.complete.call_count,before)


class ManifestTests(unittest.TestCase):
    def test_batch_errors_do_not_hide_valid_rows(self):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'samples.jsonl'
            sample=contract['example_input']
            path.write_text(json.dumps(sample)+'\n'+json.dumps(sample)+'\n{invalid json}\n',encoding='utf-8')
            result=validate_manifest(contract,path)
            self.assertFalse(result['valid'])
            self.assertEqual([x['valid'] for x in result['samples']],[True,False,False])

    @patch('builtins.input', return_value='/quit')
    def test_resume_interactive_without_model_request(self,_):
        from vision_rsi.training_cli import main
        import contextlib,io
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root)
            session=store.create('test','goal')['session_id']
            store.define(session,json.loads(Path('examples/interface-contract.json').read_text()))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                main(['show','--session-id',session,'--interactive','--sessions',root])
            self.assertIn(session,output.getvalue())
            self.assertEqual(len(store.list()),1)

class ClarificationRegressionTests(unittest.TestCase):
    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_wrapped_response_preserves_task_and_budget_is_execution_gap(self,client):
        from vision_rsi.training_cli import summary
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        contract['budget']=None
        contract['open_questions']=['How many GPU hours?']
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root)
            session=store.create('detection','detect objects')['session_id']
            client.return_value.complete.return_value={'content':json.dumps({'contract':contract,'issues':[]})}
            result=store.clarify(session,{'model':'fixture'})
            self.assertEqual(result['status'],'task_defined')
            self.assertEqual(result['versions'][-1]['contract']['goal'],contract['goal'])
            self.assertNotIn('缺少 goal',summary(result))
            self.assertIn('无需重复说明',summary(result))
            client.return_value.complete.return_value={'content':'invalid response'}
            result=store.clarify(session,{'model':'fixture'},'goal is clear')
            self.assertEqual(result['versions'][-1]['contract']['goal'],contract['goal'])

    def test_legacy_nested_session_is_readable_without_overwriting_history(self):
        with tempfile.TemporaryDirectory() as root:
            store=Sessions(root)
            session=store.create('legacy','goal')['session_id']
            contract=json.loads(Path('examples/interface-contract.json').read_text())
            with store.db() as db:
                db.execute('UPDATE sessions SET versions=? WHERE id=?',(json.dumps([{'version':1,'contract':{'contract':contract},'issues':['missing goal']}]),session))
            result=store.show(session)
            self.assertEqual(result['status'],'ready_for_harness')
            self.assertIn('raw_contract',result['versions'][0])
            with store.db() as db:
                raw=json.loads(db.execute('SELECT versions FROM sessions WHERE id=?',(session,)).fetchone()[0])
            self.assertIn('contract',raw[0]['contract'])

class SchemaSafetyTests(unittest.TestCase):
    def test_unused_output_fields_are_validated(self):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        contract['output_schema']['properties']['unused']={'type':'array','items':{'type':'mystery'}}
        self.assertTrue(any('unknown schema type' in x for x in issues(contract)))

    def test_missing_budget_does_not_hide_invalid_example(self):
        contract=json.loads(Path('examples/interface-contract.json').read_text())
        contract['budget']={}
        contract['example_input']={'sample_id':'bad','inputs':{}}
        errors=issues(contract)
        self.assertTrue(any('预算' in x for x in errors))
        self.assertTrue(any('示例不符合接口' in x for x in errors))

    def test_malformed_bounds_raise_value_error(self):
        with self.assertRaises(ValueError):
            validate_schema({'type':'number','minimum':'zero'},1)
