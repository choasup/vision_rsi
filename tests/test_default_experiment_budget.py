import copy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions, GPU_BUDGET_QUESTION, default_experiment_budget
from vision_rsi.training_runs import TrainingRuns
from test_training_runs import plan, REMOTE


class DefaultExperimentBudgetTests(unittest.TestCase):
    def test_new_contract_defaults_without_changing_explicit_or_invalid_budgets(self):
        contract={'budget':None,'open_questions':[GPU_BUDGET_QUESTION,'Which labels?']}
        original=copy.deepcopy(contract)
        result=default_experiment_budget(contract)
        self.assertEqual(result['budget'],{'gpu_hours':100})
        self.assertEqual(result['gpu_budget_scope'],'experiment')
        self.assertEqual(result['open_questions'],['Which labels?'])
        self.assertEqual(contract,original)
        for budget in ({'gpu_hours':0},{'gpu_hours':32},'invalid'):
            explicit=dict(contract,budget=budget)
            self.assertEqual(default_experiment_budget(explicit),explicit)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_clarification_applies_default_and_does_not_ask_for_gpu_hours(self,client):
        contract=json.loads(Path('examples/interface-contract.json').read_text(encoding='utf-8'))
        contract.update(budget=None,open_questions=[GPU_BUDGET_QUESTION])
        client.return_value.complete.return_value={'content':json.dumps(contract)}
        with tempfile.TemporaryDirectory() as directory:
            sessions=Sessions(directory)
            session=sessions.create('default-budget','Detect objects')
            result=sessions.clarify(session['session_id'],{},'Use the default budget')
            saved=result['versions'][-1]['contract']
            self.assertEqual(saved['budget'],{'gpu_hours':100})
            self.assertEqual(saved['gpu_budget_scope'],'experiment')
            self.assertNotIn(GPU_BUDGET_QUESTION,saved['open_questions'])
            prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
            self.assertIn('Do not ask for GPU budget',prompt['missing_gpu_budget_question'])

    def test_rounds_are_independent_but_retries_share_the_original_cap(self):
        with tempfile.TemporaryDirectory() as directory, closing(TrainingRuns(directory)) as ledger:
            first=plan('round-one')
            first['contract'].update(budget={'gpu_hours':100},gpu_budget_scope='experiment')
            first['scheduler'].update(timeout_seconds=360000-5,gpu_hours_budget=100)
            record,created=ledger.reserve(first,REMOTE)
            self.assertTrue(created)
            self.assertEqual(record['reserved_gpu_hours'],100)
            self.assertEqual(ledger.remaining('session',100,'round-one'),0)
            self.assertFalse(ledger.reserve(first,REMOTE)[1])
            with self.assertRaisesRegex(ValueError,'budget'):
                ledger.reserve(first,REMOTE,attempt='retry',cap_to_remaining=True)
            ledger.update(record['run_id'],'interrupted',record['details'],actual=40)
            retry,_=ledger.reserve(first,REMOTE,attempt='resume',cap_to_remaining=True)
            self.assertEqual(retry['reserved_gpu_hours'],60)
            self.assertEqual(ledger.remaining('session',100,'round-one'),0)
            second=copy.deepcopy(first);second['plan_id']='round-two'
            next_run,_=ledger.reserve(second,REMOTE)
            self.assertEqual(next_run['reserved_gpu_hours'],100)
            self.assertEqual(ledger.remaining('session',100,'round-two'),0)

    def test_existing_session_accounting_cannot_be_reset_by_changing_scope(self):
        with tempfile.TemporaryDirectory() as directory, closing(TrainingRuns(directory)) as ledger:
            ledger.reserve(plan(),REMOTE)
            changed=plan('new-round')
            changed['contract']['gpu_budget_scope']='experiment'
            with self.assertRaisesRegex(ValueError,'cannot be converted'):
                ledger.reserve(changed,REMOTE)
