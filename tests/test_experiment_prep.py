import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions, brief_questions, task_questions, issues
from vision_rsi.experiment_prep import prepare
from vision_rsi.harness import build
from vision_rsi.task_harness import configured_resources


class ExperimentPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.contract=json.loads(Path('examples/interface-contract.json').read_text())
        self.contract['data_source']={'kind':'local','location':str(self.root),'download_allowed':False}
        self.contract['acceptance'].update(mode='baseline',threshold=None)
        self.contract['budget']=None
        self.contract['open_questions']=['应该选什么优化器？','应该训练多少轮？']
        self.store=Sessions(self.root/'sessions')
        self.sid=self.store.create('brief','分类')['session_id']

    def test_four_fields_prepare_without_threshold_or_gpu_and_build_real_interface(self):
        session=self.store.define(self.sid,self.contract)
        self.assertEqual(task_questions(self.contract),[])
        self.assertIn('缺少有限数值验收阈值',issues(self.contract))
        report=prepare(session,self.root/'prep')
        self.assertTrue(report['data']['exists'])
        self.assertFalse(report['data']['dataset_validated'])
        self.assertFalse(report['training_performed'])
        self.assertTrue(Path(report['report_path']).is_file())
        bundle=build(session,self.root/'interface')
        self.assertTrue((Path(bundle['directory'])/'harness.py').is_file())
        self.assertEqual(configured_resources(self.contract)['clarification_questions'],[])

    def test_missing_source_asks_only_source_and_does_not_create_preparation(self):
        self.contract['data_source']=None
        self.assertEqual(len(brief_questions(self.contract)),1)
        self.assertIn('数据',brief_questions(self.contract)[0])
        with self.assertRaises(ValueError):prepare(self.store.define(self.sid,self.contract),self.root/'prep')
        self.assertFalse((self.root/'prep').exists())

    def test_nonexistent_path_and_public_source_are_not_treated_as_bound_data(self):
        self.contract['data_source']['location']=str(self.root/'missing')
        result=prepare(self.store.define(self.sid,self.contract),self.root/'prep')
        self.assertFalse(result['data']['exists'])
        self.assertIn('修正',result['next_step'])
        self.contract['data_source']={'kind':'public','location':'猫狗公开图片','download_allowed':False}
        result=prepare(self.store.define(self.sid,self.contract),self.root/'prep')
        self.assertFalse(result['data']['download_allowed'])
        self.assertFalse(result['data']['download_performed'])

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_refining_pending_draft_keeps_working_draft_and_active_contract_separate(self,client):
        active=copy.deepcopy(self.contract)
        active['acceptance'].update(mode='target',threshold=80)
        active=self.store.define(self.sid,active)['versions'][-1]['contract']
        proposed=copy.deepcopy(active);proposed['goal']='更改后的分类目标'
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        first=self.store.clarify(self.sid,{},'修改目标')
        self.assertTrue(first['versions'][-1]['review_required'])
        refined=copy.deepcopy(proposed);refined['assumptions'].append('使用默认优化器')
        client.return_value.complete.return_value={'content':json.dumps(refined)}
        result=self.store.clarify(self.sid,{},'其他实现由你决定')
        prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
        self.assertEqual(prompt['previous_contract'],proposed)
        self.assertEqual(prompt['active_contract'],active)
        self.assertTrue(any(turn['role']=='assistant' for turn in prompt['recent_dialogue']))
        self.assertEqual(result['versions'][-1]['contract'],active)
        self.assertEqual(result['versions'][-1]['proposed_contract'],refined)
        with self.assertRaises(ValueError):prepare(result,self.root/'prep')

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_omitted_source_is_preserved(self,client):
        self.store.define(self.sid,self.contract)
        response=copy.deepcopy(self.contract);response.pop('data_source')
        client.return_value.complete.return_value={'content':json.dumps(response)}
        result=self.store.clarify(self.sid,{},'优化器由你决定')
        self.assertEqual(result['versions'][-1]['contract']['data_source'],self.contract['data_source'])

    def test_interactive_show_automatically_prepares_without_api(self):
        import contextlib
        import io
        from vision_rsi.training_cli import main
        self.store.define(self.sid,self.contract)
        output=io.StringIO()
        with patch('builtins.input',side_effect=['/quit']), patch('vision_rsi.contracts.OpenAICompatibleClient') as client, contextlib.redirect_stdout(output):
            main(['show','--session-id',self.sid,'--sessions',str(self.root/'sessions'),
                  '--harness-root',str(self.root/'prep'),'--interactive'])
        client.assert_not_called()
        self.assertIn('四项需求已齐全，已进入实验准备',output.getvalue())
        self.assertNotIn('接下来请回答',output.getvalue())
        self.assertEqual(len(list((self.root/'prep').rglob('experiment-preparation.json'))),1)

    def test_malformed_acceptance_remains_a_validation_error(self):
        self.contract['acceptance']='invalid'
        with self.assertRaises(ValueError):build(self.store.define(self.sid,self.contract),self.root/'interface')

    def test_baseline_does_not_relax_invalid_numeric_target(self):
        self.contract['acceptance']['threshold']='eighty'
        with self.assertRaises(ValueError):build(self.store.define(self.sid,self.contract),self.root/'interface')


if __name__=='__main__':unittest.main()
