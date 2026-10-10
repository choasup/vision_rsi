import base64
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from test_acceptance import evidence,wrap
from test_coco_train import fixture_recipe
from vision_rsi.experiments import compile_plan,propose_next,rejected_feedback
from vision_rsi.runner import digest


def proposal():
    return {'hypothesis':'Lower learning rate reduces instability','reasoning':'Measured score is below the original target; instability is only a hypothesis',
            'recipe_changes':{'learning_rate':.0005},'expected_result':'Measure AP again without assuming improvement','failure_criteria':'No repeatable improvement within the same budget'}


class ExperimentTests(unittest.TestCase):
    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_invalid_or_oversized_research_history_is_rejected_before_ledger(self,client):
        for history in ({},[{'unexpected':'field'}],[{'observation':{'text':'x'*(193*1024)}}]):
            with self.assertRaises(ValueError):
                propose_next(self.record,self.runs,self.llm,self.root/'invalid-history','same',research_history=history)
        self.assertFalse((self.root/'invalid-history').exists());client.assert_not_called()

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_historical_measurement_is_in_prompt_and_bound_to_cached_request(self,client):
        from vision_rsi.strategy_context import history_context
        history=history_context([{'action':{'id':'analyze-old','kind':'analyze'},'status':'completed',
            'result':{'run_id':'old-run','actual_gpu_hours':.1,'acceptance_review':{'box_AP':40,'threshold':60},
                      'api_key':'MUST_NOT_FORWARD'}}])
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        folder=self.root/'memory'
        result=propose_next(self.record,self.runs,self.llm,folder,'memory',research_history=history)
        prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
        self.assertEqual(prompt['research_history'][0]['observation']['measurement']['value'],40)
        self.assertNotIn('MUST_NOT_FORWARD',json.dumps(prompt))
        self.assertEqual(result,propose_next(self.record,self.runs,self.llm,folder,'memory',research_history=history))
        changed=copy.deepcopy(history);changed[0]['observation']['measurement']['value']=41
        with self.assertRaisesRegex(ValueError,'context changed'):
            propose_next(self.record,self.runs,self.llm,folder,'memory',research_history=changed)
        self.assertEqual(client.return_value.complete.call_count,1)

    def test_feedback_is_bounded_and_excludes_other_parent_receipts(self):
        folder=self.root/'bounded-feedback';folder.mkdir()
        context={'run_id':'same','parent_plan_id':'same-plan','receipt_sha256':'same-receipt'}
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE requests(id TEXT,context TEXT,state TEXT,response TEXT)')
            for index in range(12):
                request='request-'+str(index)
                saved=dict(context)
                if index==11:saved['receipt_sha256']='other-receipt'
                db.execute('INSERT INTO requests VALUES (?,?,?,?)',(request,json.dumps(saved),'responded',json.dumps({'content':'x'*8000})))
                path=folder/request;path.mkdir()
                (path/'experiment.json').write_text(json.dumps({'status':'proposal_rejected','reason':'y'*2000}),encoding='utf-8')
            feedback=rejected_feedback(db,folder,context)
        self.assertEqual([row['request_id'] for row in feedback],['request-'+str(i) for i in range(3,11)])
        self.assertTrue(all(len(row['reason'])==1000 and len(row['proposal_content'])==6000 for row in feedback))

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_rejected_proposal_feedback_is_bound_and_replay_does_not_refresh_snapshot(self,client):
        invalid=proposal();invalid['recipe_changes']={'world_size':8}
        client.return_value.complete.side_effect=[{'content':json.dumps(invalid)},{'content':json.dumps(proposal())}]
        folder=self.root/'feedback'
        rejected=propose_next(self.record,self.runs,self.llm,folder,'invalid-first')
        self.assertEqual(rejected['status'],'proposal_rejected')
        second=propose_next(self.record,self.runs,self.llm,folder,'corrected-second')
        self.assertEqual(second['status'],'ready_to_submit')
        prompt=json.loads(client.return_value.complete.call_args.args[0][1]['content'])
        feedback=prompt['previous_rejections']
        self.assertEqual(feedback[0]['request_id'],'invalid-first')
        self.assertIn('supported',feedback[0]['reason'])
        with closing(sqlite3.connect(folder/'requests.sqlite3')) as db:
            context=json.loads(db.execute('SELECT context FROM requests WHERE id=?',('corrected-second',)).fetchone()[0])
        self.assertEqual(context['previous_rejections'],feedback)
        self.assertEqual(rejected,propose_next(self.record,self.runs,self.llm,folder,'invalid-first'))
        self.assertEqual(second,propose_next(self.record,self.runs,self.llm,folder,'corrected-second'))
        self.assertEqual(client.return_value.complete.call_count,2)

    def test_two_generation_lineage_rejects_return_to_original_method(self):
        first=compile_plan(self.parent,self.record,proposal(),.5,self.root/'first')
        frozen=json.loads(Path(first['plan_path']).read_text(encoding='utf-8'))
        self.assertEqual(frozen['experiment']['method_ancestry'],[self.parent['recipe']])
        record=dict(self.record,plan_id=first['plan_id'])
        repeated=proposal();repeated['recipe_changes']={'learning_rate':self.parent['recipe']['learning_rate']}
        with self.assertRaisesRegex(ValueError,'repeats an ancestor'):
            compile_plan(frozen,record,repeated,.4,self.root/'repeat')
        self.assertFalse((self.root/'repeat').exists())
        changed=proposal();changed['recipe_changes']={'learning_rate':.00025}
        second=compile_plan(frozen,record,changed,.4,self.root/'second')
        self.assertEqual(second['experiment']['method_ancestry'],[self.parent['recipe'],frozen['recipe']])

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_lineage_reaches_prompt_and_duplicate_response_is_cached_rejection(self,client):
        ancestor=dict(self.parent['recipe'],learning_rate=.0005)
        self.parent['experiment']={'method_ancestry':[ancestor]}
        Path(self.record['details']['plan_path']).write_text(json.dumps(self.parent),encoding='utf-8')
        self.record['plan_id']=digest(self.parent)
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        folder=self.root/'duplicate'
        first=propose_next(self.record,self.runs,self.llm,folder,'same')
        self.assertEqual(first['status'],'proposal_rejected')
        self.assertIn('ancestor',first['reason'])
        self.assertEqual(first,propose_next(self.record,self.runs,self.llm,folder,'same'))
        self.assertEqual(client.return_value.complete.call_count,1)
        messages=client.return_value.complete.call_args.args[0]
        prompt=json.loads(messages[1]['content'])
        self.assertEqual(len(prompt['previous_methods_in_lineage']),2)
        self.assertEqual(prompt['previous_methods_in_lineage'][0]['learning_rate'],.0005)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_malformed_lineage_blocks_before_api_or_request_ledger(self,client):
        self.parent['experiment']={'method_ancestry':[{'learning_rate':.0005}]}
        Path(self.record['details']['plan_path']).write_text(json.dumps(self.parent),encoding='utf-8')
        self.record['plan_id']=digest(self.parent)
        with self.assertRaises((ValueError,KeyError)):
            propose_next(self.record,self.runs,self.llm,self.root/'invalid-lineage','invalid')
        client.assert_not_called()
        self.assertFalse((self.root/'invalid-lineage').exists())

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        parent,receipt=evidence(score=42)
        parent.update(task_id='task',session_id='session',status='ready_to_submit',blockers=[],
                      scheduler={'gpu_devices':[0],'timeout_seconds':40,'gpu_hours_budget':1})
        parent['contract']['budget']={'gpu_hours':1}
        parent['recipe']=dict(fixture_recipe('.'),coco_root='/remote/coco',weights='/remote/weights.pth',fixture=False,
                              acceptance_threshold=60,val_annotations_sha256='a'*64)
        result=json.loads(base64.b64decode(receipt['reports']['result.json']['base64']))
        result['identity']['recipe']=parent['recipe'];result['identity_hash']=digest(result['identity'])
        receipt['reports']['result.json']=wrap(result);receipt['run_id']='train-'+'a'*32
        self.parent=parent
        path=self.root/'parent.json';path.write_text(json.dumps(parent));rp=self.root/'receipt.json';rp.write_text(json.dumps(receipt))
        self.record={'run_id':receipt['run_id'],'status':'completed','actual_gpu_hours':.01,'plan_id':digest(parent),
                     'details':{'plan_path':str(path),'receipt_path':str(rp),'deployment':{'directory':'/workspace/releases/frozen'}}}
        self.runs=MagicMock();self.runs.remaining.return_value=.5
        self.llm={'model':'fixture','base_url':'https://fixture.invalid'}

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_cached_method_request_rejects_different_usage_ledger(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        config=dict(self.llm,usage_ledger=str(self.root/'usage.sqlite3'),usage_call_limit=2)
        folder=self.root/'bound-ledger'
        first=propose_next(self.record,self.runs,config,folder,'bound')
        self.assertEqual(first,propose_next(self.record,self.runs,config,folder,'bound'))
        for changed in (dict(config,usage_ledger=str(self.root/'other.sqlite3')),
                        dict(config,usage_call_limit=3),self.llm):
            with self.assertRaisesRegex(ValueError,'context changed'):
                propose_next(self.record,self.runs,changed,folder,'bound')
        self.assertEqual(client.return_value.complete.call_count,1)

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_not_dispatched_is_durable_and_requires_explicit_new_id(self,client):
        from vision_rsi.llm import LLMNotDispatched
        client.return_value.complete.side_effect=LLMNotDispatched('local cap exhausted')
        folder=self.root/'not-sent'
        for _ in range(2):
            with self.assertRaises(LLMNotDispatched):
                propose_next(self.record,self.runs,self.llm,folder,'same-id')
        self.assertEqual(client.return_value.complete.call_count,1)
        with closing(sqlite3.connect(folder/'requests.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state,response FROM requests').fetchone(),('not_dispatched',None))
        client.return_value.complete.side_effect=None
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        result=propose_next(self.record,self.runs,self.llm,folder,'explicit-new-id')
        self.assertEqual(result['status'],'ready_to_submit')

    def test_missing_key_does_not_reserve_method_request(self):
        with patch.dict('os.environ',{'VISION_RSI_UNSET':''}), patch('vision_rsi.llm.urlopen') as http:
            config=dict(self.llm,api_key_env='VISION_RSI_UNSET')
            folder=self.root/'preflight-research'
            with self.assertRaises(ValueError):propose_next(self.record,self.runs,config,folder,'preflight-missing')
            with closing(sqlite3.connect(folder/'requests.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0)
            http.assert_not_called()

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_unenforced_task_caps_block_method_api_and_compilation(self,client):
        parent=copy.deepcopy(self.parent)
        parent['contract']['budget']['llm_calls']=0
        with self.assertRaisesRegex(ValueError,'cannot enforce budget.llm_calls'):
            compile_plan(parent,self.record,proposal(),.5,self.root/'blocked-plans')
        Path(self.record['details']['plan_path']).write_text(json.dumps(parent))
        record=dict(self.record,plan_id=digest(parent))
        with self.assertRaisesRegex(ValueError,'cannot enforce budget.llm_calls'):
            propose_next(record,self.runs,self.llm,self.root/'blocked-research','blocked-caps')
        client.assert_not_called()
        self.assertFalse((self.root/'blocked-research').exists())

    def test_method_change_keeps_data_model_threshold_sources_and_budget_frozen(self):
        original=copy.deepcopy(self.parent)
        plan=compile_plan(self.parent,self.record,proposal(),.003,self.root/'plans')
        self.assertEqual(self.parent,original)
        self.assertEqual(plan['recipe']['learning_rate'],.0005)
        for field in ('detector','weights','weights_sha256','coco_root','val_annotations_sha256','seed','world_size','fixture','acceptance_threshold'):
            self.assertEqual(plan['recipe'][field],original['recipe'][field])
        self.assertEqual(plan['contract'],original['contract']);self.assertEqual(plan['source_hashes'],original['source_hashes'])
        self.assertLessEqual((plan['scheduler']['timeout_seconds']+5)/3600,.003)
        self.assertEqual(digest(json.loads(Path(plan['plan_path']).read_text())),plan['plan_id'])

    def test_forbidden_changes_and_insufficient_budget_rejected(self):
        for field,value in [('acceptance_threshold',1),('fixture',True),('weights','/different'),('coco_root','/other'),('world_size',8),('seed',9)]:
            changed=proposal();changed['recipe_changes'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):compile_plan(self.parent,self.record,changed,.5,self.root/'plans')
        with self.assertRaises(ValueError):compile_plan(self.parent,self.record,proposal(),.001,self.root/'plans')

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_strategy_brief_reaches_planner_and_is_bound_to_plan_and_request(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        brief='Use the measured target gap to test lower LR; do not infer instability from AP alone.'
        result=propose_next(self.record,self.runs,self.llm,self.root/'research','directed',research_brief=brief)
        messages=client.return_value.complete.call_args.args[0]
        self.assertEqual(json.loads(messages[1]['content'])['strategy_research_brief'],brief)
        self.assertEqual(result['experiment']['strategy_research_brief'],brief)
        self.assertEqual(result['experiment']['strategy_brief_sha256'],digest(brief))
        with self.assertRaisesRegex(ValueError,'context changed'):
            propose_next(self.record,self.runs,self.llm,self.root/'research','directed',research_brief='Changed hypothesis')
        client.return_value.complete.assert_called_once()

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_proposal_response_reused_and_original_receipt_rechecked(self,client):
        client.return_value.complete.return_value={'content':json.dumps(proposal()),'model':'fixture'}
        first=propose_next(self.record,self.runs,self.llm,self.root/'research','request-one')
        self.assertEqual(first['status'],'ready_to_submit')
        self.assertEqual(first,propose_next(self.record,self.runs,self.llm,self.root/'research','request-one'))
        client.return_value.complete.assert_called_once()
        Path(self.record['details']['plan_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'parent Training plan changed'):
            propose_next(self.record,self.runs,self.llm,self.root/'research','request-one')

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_uncertain_api_not_retried_and_exhausted_budget_never_calls(self,client):
        client.return_value.complete.side_effect=TimeoutError('response uncertain')
        with self.assertRaises(TimeoutError):propose_next(self.record,self.runs,self.llm,self.root/'research','request-two')
        with self.assertRaisesRegex(RuntimeError,'Uncertain experiment API'):
            propose_next(self.record,self.runs,self.llm,self.root/'research','request-two')
        client.return_value.complete.assert_called_once()
        self.runs.remaining.return_value=0
        result=propose_next(self.record,self.runs,self.llm,self.root/'research','request-three')
        self.assertEqual(result['status'],'budget_exhausted');client.return_value.complete.assert_called_once()

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_unsafe_model_proposal_recorded_but_never_ready(self,client):
        changed=proposal();changed['recipe_changes']['acceptance_threshold']=1
        client.return_value.complete.return_value={'content':json.dumps(changed)}
        result=propose_next(self.record,self.runs,self.llm,self.root/'research','request-four')
        self.assertEqual(result['status'],'proposal_rejected')
        self.assertFalse(result['training_performed'])

    @patch('vision_rsi.llm.OpenAICompatibleClient')
    def test_deep_method_database_response_and_plan_replay(self,client):
        from vision_rsi.filesystem import native_path
        client.return_value.complete.return_value={'content':json.dumps(proposal())}
        root=self.root;owned=[]
        for i in range(8):
            root=root/('owned-segment-'+str(i)+'-'+'x'*22);owned.append(root)
        root=native_path(root)
        try:
            first=propose_next(self.record,self.runs,self.llm,root,'deep-request')
            self.assertGreater(len(first['plan_path']),260)
            self.assertEqual(json.loads(Path(first['plan_path']).read_text())['status'],'ready_to_submit')
            self.assertEqual(first,propose_next(self.record,self.runs,self.llm,root,'deep-request'))
            self.assertEqual(client.return_value.complete.call_count,1)
            self.assertTrue(native_path(root/'deep-request/response.json').is_file())
        finally:
            if root.exists():
                for path in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True):
                    if path.is_file():path.unlink()
                    elif path.is_dir():path.rmdir()
                root.rmdir()
            for directory in reversed(owned[:-1]):
                directory=native_path(directory)
                if directory.exists():directory.rmdir()
