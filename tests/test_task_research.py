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
    def test_first_model_request_receives_task_interface_before_candidate_exists(self,client,execute):
        with tempfile.TemporaryDirectory() as folder:
            store,session=self.task(folder)
            client.return_value.complete.return_value={'content':json.dumps({'tool':'inspect_repository','summary':'inspect',
                'question':'q','expected_evidence':'e','refs':['objective']})}
            result=advance(session,{'llm':{'model':'fixture'}},Path(folder)/'research',steps=1)
            prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
            self.assertEqual(prompt['frozen_task_contract']['sha256'],result['task_contract']['sha256'])
            self.assertEqual(prompt['frozen_task_contract']['contract'],session['versions'][-1]['contract'])

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


if __name__=='__main__':unittest.main()
