import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.contracts import Sessions
from vision_rsi.task_research import prepare,advance


class TaskResearchTests(unittest.TestCase):
    @patch('vision_rsi.controller.execute',return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_pause_during_planning_preserves_response_and_resume_uses_no_new_api(self,client,execute):
        from vision_rsi.task_research import control,status
        with tempfile.TemporaryDirectory() as folder:
            _,session=self.task(folder)
            root=Path(folder)/'research'
            prepare(session,root)
            config={'llm':{'model':'fixture'},'research':{'max_planning_requests':1}}
            def planning(*args,**kwargs):
                control(session,'pause',root)
                return {'content':json.dumps({'tool':'inspect_repository','summary':'inspect',
                    'question':'q','expected_evidence':'e','refs':['objective']})}
            client.return_value.complete.side_effect=planning
            with self.assertRaises(ValueError):advance(session,config,root,steps=1)
            execute.assert_not_called()
            paused=status(session,root)
            self.assertEqual(paused['research_status']['state'],'paused')
            self.assertEqual(paused['research_status']['planning_attempts_used'],1)
            repeated=control(session,'pause',root)
            self.assertFalse(repeated['control_changed'])
            self.assertEqual(repeated['events'],paused['events'])
            resumed=control(session,'resume',root)
            self.assertEqual(resumed['research_status']['state'],'cached_response_available')
            advance(session,config,root,steps=1)
            self.assertEqual(client.return_value.complete.call_count,1)
            self.assertEqual(execute.call_count,1)
            self.assertEqual(status(session,root)['research_status']['state'],'planning_limit_exhausted')

    def test_status_is_read_only_and_missing_ledger_is_not_created(self):
        from vision_rsi.task_research import status
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            _,session=self.task(folder)
            root=Path(folder)/'research'
            with self.assertRaises(sqlite3.OperationalError):status(session,root)
            self.assertFalse(root.exists())
            prepared=prepare(session,root)
            directory=Path(prepared['directory'])
            before={p.name:p.read_bytes() for p in directory.iterdir()
                    if p.is_file() and not p.name.endswith(('-wal','-shm'))}
            result=status(session,root)
            self.assertEqual(result['research_status']['state'],'manual_step_available')
            self.assertEqual(result['research_status']['limit_source'],'default_not_frozen')
            # SQLite mode=ro can create WAL shared-memory sidecars; canonical files remain unchanged.
            self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()
                                    if p.is_file() and not p.name.endswith(('-wal','-shm'))})
            (directory/'contract.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):status(session,root)

    @patch('vision_rsi.controller.execute',return_value={'observed':True})
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_first_model_request_receives_task_interface_before_candidate_exists(self,client,execute):
        with tempfile.TemporaryDirectory() as folder:
            store,session=self.task(folder)
            client.return_value.complete.return_value={'content':json.dumps({'tool':'inspect_repository','summary':'inspect',
                'question':'q','expected_evidence':'e','refs':['objective']})}
            context={'session_id':session['session_id'],'task_id':session['task_id'],
                     'contract_version':session['versions'][-1]['version'],'authorized_gpu_hours':None,
                     'unsettled_run_ids':['uncertain-run'],'task_quality_status':'not_checked'}
            result=advance(session,{'llm':{'model':'fixture'}},Path(folder)/'research',steps=1,task_context=context)
            prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
            self.assertEqual(prompt['frozen_task_contract']['sha256'],result['task_contract']['sha256'])
            self.assertEqual(prompt['frozen_task_contract']['contract'],session['versions'][-1]['contract'])
            self.assertEqual(prompt['task_readiness'],context)
            self.assertNotIn('synthesize',prompt['available_tools'])
            self.assertEqual(prompt['schema']['tool'],prompt['available_tools'])
            self.assertIn('NOT successful tool evidence',prompt['instruction'])

    def task(self,folder):
        store=Sessions(Path(folder)/'sessions')
        session=store.create('fixture-task','detailed task requirement')
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
        store.define(session['session_id'],contract)
        return store,store.show(session['session_id'])

    def test_binding_is_repeatable_and_cannot_replace_contract_or_task_version(self):
        with tempfile.TemporaryDirectory() as folder:
            store,session=self.task(folder);db=store.root/'sessions.sqlite3';before=db.read_bytes()
            root=Path(folder)/'research'
            first=prepare(session,root);second=prepare(session,root)
            self.assertEqual(first,second)
            self.assertEqual(before,db.read_bytes())
            contract_path=Path(first['task_contract']['path'])
            self.assertEqual(hashlib.sha256(contract_path.read_bytes()).hexdigest(),first['task_contract']['sha256'])
            changed=dict(session,turns=session['turns']+[{'role':'user','content':'changed requirement'}])
            with self.assertRaisesRegex(ValueError,'Task changed'):prepare(changed,root)
            contract_path.write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'contract changed'):prepare(session,root)

    @patch('vision_rsi.task_research.research_step',return_value={'events':2})
    def test_advance_uses_exported_contract_and_preserves_candidate_permissions(self,step):
        with tempfile.TemporaryDirectory() as folder:
            store,session=self.task(folder)
            config={'llm':{'model':'fixture'},'research':{'allow_candidate_writes':False}}
            result=advance(session,config,Path(folder)/'research',steps=1,repository=folder)
            called=step.call_args.args[0]
            self.assertEqual(called['research']['task_contract'],result['task_contract'])
            self.assertFalse(called['research']['allow_candidate_writes'])
            self.assertNotIn('task_contract',config['research'])
            with self.assertRaises(ValueError):prepare(dict(session,pending_request=True),Path(folder)/'pending')
            context={'session_id':session['session_id'],'task_id':session['task_id'],
                     'contract_version':session['versions'][-1]['version'],'authorized_gpu_hours':None,
                     'unsettled_run_ids':['training-uncertain'],'task_quality_status':'not_checked'}
            advance(session,config,Path(folder)/'research',steps=1,task_context=context)
            self.assertEqual(step.call_args.args[0]['_task_readiness_context'],context)
            with self.assertRaisesRegex(ValueError,'readiness does not match'):
                advance(session,config,Path(folder)/'research',task_context=dict(context,contract_version=999))


if __name__=='__main__':unittest.main()
