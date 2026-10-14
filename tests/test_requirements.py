import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.contracts import Sessions
from vision_rsi.requirements import changes


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Sessions(self.temp.name)
        self.contract=json.loads(Path('examples/interface-contract.json').read_text())
        self.contract['acceptance'].update(threshold=60,direction='maximize')
        self.session=self.store.create('vision-task','Keep task requirements')['session_id']
        self.store.define(self.session,self.contract)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_model_cannot_silently_weaken_task_or_expand_budget(self,client):
        proposed=copy.deepcopy(self.contract)
        proposed['acceptance']['threshold']=40
        proposed['budget']={'gpu_hours':10000}
        proposed['inputs']={}
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        result=self.store.clarify(self.session,{'model':'fixture'},'Please continue')
        self.assertEqual(result['status'],'requirements_review')
        latest=result['versions'][-1]
        self.assertEqual(latest['contract'],self.contract)
        self.assertEqual(latest['proposed_contract'],proposed)
        self.assertEqual({x['path'] for x in latest['review_required']},{'acceptance.threshold','budget','inputs'})
        self.assertFalse(result['pending_request'])
        from vision_rsi.harness import build
        from vision_rsi.campaign import advance
        with self.assertRaisesRegex(ValueError,'requirements'):build(result,Path(self.temp.name)/'harness')
        with self.assertRaisesRegex(ValueError,'requirements'):advance(result,{},Path(self.temp.name)/'campaign')
        from vision_rsi.training_plan import prepare
        plan=prepare(result,{'remote':{}},Path(self.temp.name)/'plans')
        self.assertEqual(plan['status'],'blocked')
        self.assertEqual(plan['contract']['acceptance']['threshold'],60)
        self.assertTrue(any('acceptance.threshold' in x for x in plan['blockers']))

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_exact_version_accept_and_reject_are_persisted(self,client):
        proposed=copy.deepcopy(self.contract);proposed['acceptance']['threshold']=65
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        self.store.clarify(self.session,{'model':'fixture'},'Raise requirement')
        with self.assertRaises(ValueError):self.store.accept(self.session,1)
        accepted=self.store.accept(self.session,2)
        self.assertEqual(accepted['versions'][-1]['contract']['acceptance']['threshold'],65)
        self.assertEqual(accepted['versions'][-1]['reviewed_draft_version'],2)
        with self.assertRaises(ValueError):self.store.accept(self.session,2)
        client.return_value.complete.return_value={'content':json.dumps(self.contract)}
        self.store.clarify(self.session,{'model':'fixture'},'Review another proposal')
        rejected=self.store.reject(self.session,4)
        self.assertEqual(rejected['versions'][-1]['contract']['acceptance']['threshold'],65)
        self.assertNotIn('review_required',rejected['versions'][-1])
        self.assertEqual(rejected['versions'][-1]['origin'],'user_rejected_model_draft')

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_assumptions_and_questions_can_be_refined_without_contract_change(self,client):
        proposed=copy.deepcopy(self.contract);proposed['assumptions']=['Model choice is delegated'];proposed['open_questions']=[]
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        result=self.store.clarify(self.session,{'model':'fixture'},'Choose implementation yourself')
        self.assertNotIn('review_required',result['versions'][-1])
        self.assertEqual(result['versions'][-1]['contract'],proposed)

    def test_protocol_goal_schema_and_numeric_types_are_protected(self):
        for field in ('goal','inputs','output_schema','acceptance','budget'):
            proposed=copy.deepcopy(self.contract);proposed.pop(field)
            self.assertTrue(changes(self.contract,proposed))
        self.assertTrue(changes({'budget':{'gpu_hours':1}},{'budget':{'gpu_hours':True}}))
        self.assertEqual(changes({'budget':None},{'budget':{}}),[])

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_nonfinite_model_response_keeps_previous_contract(self,client):
        proposed=copy.deepcopy(self.contract);proposed['acceptance']['threshold']=float('nan')
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        result=self.store.clarify(self.session,{'model':'fixture'},'Continue')
        self.assertEqual(result['versions'][-1]['contract'],self.contract)
        self.assertTrue(any('解析失败' in x for x in result['versions'][-1]['issues']))

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_null_or_array_response_keeps_previous_contract_and_clears_known_request(self,client):
        for content in (None,'[]'):
            client.return_value.complete.return_value={'content':content}
            result=self.store.clarify(self.session,{'model':'fixture'},'Continue')
            self.assertEqual(result['versions'][-1]['contract'],self.contract)
            self.assertFalse(result['pending_request'])

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_summary_shows_diff_without_requiring_schema_edits(self,client):
        from vision_rsi.training_cli import summary
        proposed=copy.deepcopy(self.contract);proposed['acceptance']['threshold']=40
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        result=self.store.clarify(self.session,{'model':'fixture'},'Continue')
        text=summary(result)
        self.assertIn('60 → 40',text);self.assertIn('/accept',text);self.assertIn('/reject',text)

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_legacy_budget_null_is_preserved_without_confirmation(self,client):
        for budget in ({'gpu_hours':10},10):
            contract=copy.deepcopy(self.contract);contract['budget']=budget
            contract.pop('gpu_budget_scope',None)
            self.store.define(self.session,contract)
            proposed=copy.deepcopy(contract);proposed['budget']=None
            client.return_value.complete.return_value={'content':json.dumps(proposed)}
            result=self.store.clarify(self.session,{'model':'fixture'},'继续')
            self.assertEqual(result['versions'][-1]['contract']['budget'],budget)
            self.assertNotIn('review_required',result['versions'][-1])

    @patch('vision_rsi.contracts.OpenAICompatibleClient')
    def test_description_only_rewrite_does_not_require_confirmation(self,client):
        proposed=copy.deepcopy(self.contract)
        proposed['output_schema']['description']='只是解释输出格式'
        for field in proposed['inputs'].values():field['description']='模型接收的内容'
        client.return_value.complete.return_value={'content':json.dumps(proposed)}
        result=self.store.clarify(self.session,{'model':'fixture'},'继续')
        self.assertNotIn('review_required',result['versions'][-1])
        changed=copy.deepcopy(proposed)
        changed['output_schema']['properties']['new_field']={'type':'boolean'}
        self.assertTrue(changes(proposed,changed))

    def test_review_text_shows_decisions_without_model_monologue_or_dicts(self):
        from vision_rsi.training_cli import conversation_summary
        session=self.store.show(self.session)
        session['versions'][-1].update(review_required=[{'path':'data_source',
            'before':{'kind':'public','location':'公开数据','download_allowed':True},
            'after':{'kind':'public','location':'COCO','download_allowed':True}}],
            proposed_contract=self.contract,assistant_message='长篇重复解释'*100)
        text=conversation_summary(session)
        self.assertIn('数据来源：公开数据（允许下载） → COCO（允许下载）',text)
        self.assertNotIn('长篇重复解释',text)
        self.assertNotIn('download_allowed',text)
