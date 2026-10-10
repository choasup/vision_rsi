import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_acceptance import evidence
from vision_rsi.research_training import inspect,arguments
from vision_rsi.training_runs import TrainingRuns
from vision_rsi.runner import digest


class ResearchTrainingTests(unittest.TestCase):
    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_controller_reads_bound_receipt_via_model_run_id_only(self,client):
        import hashlib
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binding,run,plan=self.fixture(root)
            contract=root/'contract.json';contract.write_text(json.dumps(plan['contract']),encoding='utf-8')
            ledger=Ledger(root/'research');ledger.append('goal','objective',{'summary':'Analyze actual recorded task results'})
            config={'llm':{'model':'fixture'},'_training_evidence_context':binding,
                    '_task_readiness_context':{'recent_run_ids':[run]},
                    'research':{'task_contract':{'path':str(contract),'sha256':hashlib.sha256(contract.read_bytes()).hexdigest()}}}
            client.return_value.complete.return_value={'content':json.dumps({'tool':'read_training_run',
                'summary':'read','question':'q','expected_evidence':'recorded metrics','refs':['goal'],'arguments':{'run_id':run}})}
            research_step(config,ledger.directory)
            prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
            self.assertIn('read_training_run',prompt['available_tools'])
            observed=ledger.events()[-1]['payload']
            self.assertEqual(observed['status'],'completed')
            self.assertTrue(observed['read_only'])
            self.assertEqual(observed['observation']['receipt_review']['box_AP'],42)
            self.assertFalse(observed['observation']['receipt_review']['passed'])

    def fixture(self,root):
        plan,receipt=evidence(score=42)
        plan['session_id']='a'*32
        run='train-'+'b'*32
        receipt['run_id']=run
        path=root/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
        collected=root/'runs/artifacts'/run/digest(receipt)/'receipt.json'
        collected.parent.mkdir(parents=True)
        collected.write_text(json.dumps(receipt),encoding='utf-8')
        store=TrainingRuns(root/'runs')
        try:
            with store.db:
                store.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
                    (run,plan['session_id'],digest(plan),'{}',1,0.5,'completed',
                     json.dumps({'plan_path':str(path),'receipt_path':str(collected),
                                 'acceptance_review':{'passed':True,'box_AP':99}}),1))
        finally:store.close()
        return {'run_store':str(root/'runs'),'session_id':plan['session_id']},run,plan

    def test_recomputes_collected_metrics_instead_of_trusting_cached_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binding,run,plan=self.fixture(root)
            database=root/'runs/training-runs.sqlite3';before=database.read_bytes()
            result=inspect(binding,run,plan['contract'])
            self.assertEqual(result['receipt_review']['box_AP'],42)
            self.assertFalse(result['receipt_review']['passed'])
            self.assertFalse(result['quality_verified'])
            self.assertFalse(result['remote_called'])
            self.assertEqual(database.read_bytes(),before)

    def test_cross_task_and_changed_plan_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binding,run,plan=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'another task'):
                inspect(dict(binding,session_id='c'*32),run,plan['contract'])
            with self.assertRaisesRegex(ValueError,'frozen research task'):
                inspect(binding,run,{'acceptance':{}})
            (root/'plan.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'plan changed'):inspect(binding,run,plan['contract'])

    def test_corrupt_receipt_is_rejected_without_cached_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binding,run,plan=self.fixture(root)
            collected=next((root/'runs/artifacts').rglob('receipt.json'))
            collected.write_text(json.dumps({'run_id':run,'reports':{}}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'receipt identity changed'):inspect(binding,run,plan['contract'])

    def test_model_cannot_supply_paths_or_session_and_missing_store_not_created(self):
        for value in ({'path':'secret'}, {'run_id':'../secret'}, {'run_id':'train-'+'a'*32,'session_id':'other'}):
            with self.assertRaises(ValueError):arguments(value)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'missing'
            with self.assertRaises(ValueError):inspect({'run_store':root,'session_id':'a'*32},'train-'+'b'*32,{})
            self.assertFalse(root.exists())
