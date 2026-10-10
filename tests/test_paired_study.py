import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_coco_train import fixture_recipe
from vision_rsi.contracts import Sessions
from vision_rsi.paired_study import create,load,step,compare,paired_sign_evidence,SIGN_RULE


class PairedStudyTests(unittest.TestCase):
    def test_exact_sign_rule_counts_ties_losses_and_insufficient_replication(self):
        strong=paired_sign_evidence([2]*5,1,SIGN_RULE)
        self.assertEqual(strong['p_value'],1/32)
        self.assertTrue(strong['preregistered_sign_rule_met'])
        self.assertFalse(strong['independence_verified']);self.assertFalse(strong['agent_adopted'])
        short=paired_sign_evidence([2]*4+[1]*10,1,SIGN_RULE)
        self.assertEqual(short['non_tied_pairs'],4);self.assertEqual(short['tied_pairs'],10)
        self.assertFalse(short['preregistered_sign_rule_met'])
        mixed=paired_sign_evidence([2]*4+[0],1,SIGN_RULE)
        self.assertEqual(mixed['p_value'],6/32);self.assertFalse(mixed['preregistered_sign_rule_met'])
        ties=paired_sign_evidence([1]*5,1,SIGN_RULE)
        self.assertIsNone(ties['p_value']);self.assertFalse(ties['preregistered_sign_rule_met'])
        for gains in ([],[True],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError):paired_sign_evidence(gains,1,SIGN_RULE)
        with self.assertRaises(ValueError):paired_sign_evidence([2]*5,1,dict(SIGN_RULE,alpha=.5))

    def test_preregistration_preserves_shared_api_and_controller_caps_without_credentials(self):
        self.spec['research_rounds']=1
        ledger=str(self.root/'shared-api.sqlite3')
        self.config['llm'].update(usage_ledger=ledger,usage_call_limit=9,api_key='MUST_NOT_PERSIST')
        self.config['controller']={'tool_attempt_limit':12}
        record=self.create()
        for pair in record['identity']['pairs']:
            self.assertEqual(pair['config']['controller'],{'tool_attempt_limit':12})
            self.assertEqual(pair['config']['llm']['usage_ledger'],ledger)
            self.assertEqual(pair['config']['llm']['usage_call_limit'],9)
            for arm in ('baseline','candidate'):
                binding=pair[arm]['binding']
                self.assertEqual(binding['controller_tool_attempt_limit'],12)
                self.assertEqual(binding['research_model']['usage_ledger'],ledger)
                self.assertEqual(binding['research_model']['usage_call_limit'],9)
        self.assertNotIn('MUST_NOT_PERSIST',json.dumps(record))
        self.assertFalse(Path(ledger).exists())

    def test_invalid_caps_are_not_silently_discarded_during_preregistration(self):
        for controller in ({'tool_attempt_limit':True},{'unknown':1}):
            self.config['controller']=controller
            with self.assertRaises(ValueError):self.create()
        self.config.pop('controller')
        for llm in ({'usage_call_limit':1},{'usage_call_limit':True,'usage_ledger':str(self.root/'usage.sqlite3')},
                    {'usage_ledger':'relative.sqlite3'}):
            self.config['llm']={'model':'fixture','base_url':'https://fixture.invalid',**llm}
            with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.studies.exists())

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sessions=self.root/'sessions';self.campaigns=self.root/'campaigns';self.runs=self.root/'runs';self.studies=self.root/'studies'
        cid='a'*64;folder=self.root/'candidates'/cid;folder.mkdir(parents=True)
        self.candidate={'git_revision':'b'*40,'source_hashes':{'vision_rsi/strategy_test.py':'c'*64}}
        (folder/'candidate.json').write_text(json.dumps(self.candidate))
        self.spec={'candidate':{'candidate_id':cid,'module':'vision_rsi.strategy_test','store':str(folder.parent)},'pairs':[],
                   'research_rounds':0,'minimum_mean_ap_gain':1,'heldout_declaration':'Unit metadata only; not actual held-out provenance'}
        store=Sessions(self.sessions)
        contract={'goal':'COCO detection','inputs':{'image':{'type':'image','required':True}},
                  'output_schema':{'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}},
                  'acceptance':{'metric':'box_AP','threshold':60,'direction':'maximize','evaluation_protocol':'COCO bbox AP'},
                  'budget':{'gpu_hours':1},'assumptions':[],'open_questions':[],
                  'example_input':{'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.jpg'}}},'example_output':{'detections':[]}}
        for seed in (11,22):
            pair={'seed':seed}
            for arm in ('baseline','candidate'):
                sid=store.create('detection','COCO detection')['session_id'];store.define(sid,contract);pair[arm+'_session']=sid
            self.spec['pairs'].append(pair)
        recipe=fixture_recipe(self.root);recipe.update(fixture=False,coco_root='/data/coco',weights='/data/weights.pth')
        self.config={'remote':{'ssh_host':'fixture.invalid','workspace':'/workspace','coco_root':'/data/coco'},
                     'training':recipe,'llm':{'model':'fixture','base_url':'https://fixture.invalid','api_key_env':'UNUSED'}}
        for name,value in [('git',''),('revision','d'*40),('verify_candidate',self.candidate)]:
            mock=patch('vision_rsi.paired_study.'+name,return_value=value);mock.start();self.addCleanup(mock.stop)

    def create(self):return create(self.spec,self.config,self.studies,self.sessions,self.campaigns,self.runs)

    def test_freezes_budget_pairs_and_executes_exact_registered_arm(self):
        record=self.create();identity=record['identity']
        self.assertEqual(load(record['study_id'],self.studies),record)
        self.assertFalse(record['agent_adopted'])
        with patch('vision_rsi.paired_study.advance',return_value={'status':'waiting'}) as runner:
            self.assertEqual(step(record['study_id'],0,'candidate',self.studies),{'status':'waiting'})
            args=runner.call_args
            self.assertEqual(args.args[5]['candidate_id'],self.spec['candidate']['candidate_id'])
            self.assertEqual(args.kwargs['research_rounds'],0)
        self.assertEqual(identity['pairs'][0]['baseline']['binding']['contract'],identity['pairs'][0]['candidate']['binding']['contract'])
        path=self.studies/record['study_id']/'study.json';record['identity']['minimum_mean_ap_gain']=0
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'identity changed'):load(record['study_id'],self.studies)

    def test_unequal_budget_reused_sessions_and_prior_execution_are_refused(self):
        original=copy.deepcopy(self.spec)
        self.spec['pairs'][1]['baseline_session']=self.spec['pairs'][0]['baseline_session']
        with self.assertRaisesRegex(ValueError,'distinct session'):self.create()
        self.spec=original
        store=Sessions(self.sessions);sid=self.spec['pairs'][0]['candidate_session'];contract=store.show(sid)['versions'][-1]['contract']
        contract['budget']['gpu_hours']=2;store.define(sid,contract)
        with self.assertRaisesRegex(ValueError,'identical task'):self.create()
        contract['budget']['gpu_hours']=1;store.define(sid,contract)
        folder=self.campaigns/sid/'old';folder.mkdir(parents=True);(folder/'state.json').write_text(json.dumps({'history':[{'status':'completed'}]}))
        with self.assertRaisesRegex(ValueError,'Preregister before'):self.create()

    def test_missing_evidence_never_becomes_a_positive_comparison(self):
        record=self.create();result=compare(record['study_id'],self.studies)
        self.assertEqual(len(result['missing_evidence']),4);self.assertFalse(result['comparison_complete'])
        self.assertIsNone(result['mean_paired_ap_gain']);self.assertFalse(result['agent_adopted'])
        self.assertFalse(result['paired_statistical_evidence']['evaluated'])

    def test_all_registered_pairs_are_required_and_changed_data_is_rejected(self):
        # Fabricated audit results isolate comparison logic; no real AP evidence.
        record=self.create();identity=record['identity']
        for pair in identity['pairs']:
            for arm in ('baseline','candidate'):
                bound=pair[arm];folder=self.campaigns/bound['session_id']/bound['campaign_id'];folder.mkdir(parents=True)
                state={'binding':bound['binding'],'status':'needs_research','plan':{'status':'ready_to_submit'},'run_id':'fixture',
                       'run_status':'completed','receipt_collected':True,'analysis':{'quality_verified':False},
                       'history':[{'created_at_unix':identity['registered_at_unix']+1,'control_sources':identity['control_sources'],'git_revision':identity['git_revision']}]}
                (folder/'state.json').write_text(json.dumps(state))
        def audited(sid,*args):
            candidate=any(pair['candidate']['session_id']==sid for pair in identity['pairs'])
            pair=next(pair for pair in identity['pairs'] if sid in (pair['baseline']['session_id'],pair['candidate']['session_id']))
            from vision_rsi.training_plan import DEFAULT_RECIPE
            recipe={**DEFAULT_RECIPE,**pair['config']['training']};recipe['acceptance_threshold']=60
            arm='candidate' if candidate else 'baseline';bound=pair[arm]
            raw=(self.campaigns/sid/bound['campaign_id']/'state.json').read_bytes()
            return {'evidence_complete_for_review':True,'best_verified_real_box_AP':45 if candidate else 42,'missing_evidence':[],
                    'campaign_state_sha256':hashlib.sha256(raw).hexdigest(),
                    'measurements':[{'training_identity':{'recipe':recipe,'image_contents_sha256':'e'*64,'sources':identity['control_sources']}}]}
        with patch('vision_rsi.paired_study.audit',side_effect=audited):
            result=compare(record['study_id'],self.studies)
        self.assertTrue(result['comparison_complete']);self.assertEqual(result['mean_paired_ap_gain'],3)
        self.assertFalse(result['pairs'][0]['resource_comparison']['observed_costs_complete'])
        self.assertIsNone(result['pairs'][0]['resource_comparison']['metrics']['known_llm_tokens']['candidate_minus_baseline'])
        self.assertTrue(result['preregistered_gain_rule_met']);self.assertFalse(result['rsi_efficiency_verified']);self.assertFalse(result['agent_adopted'])
        self.assertEqual(identity['statistical_rule'],SIGN_RULE)
        self.assertEqual(result['paired_statistical_evidence']['p_value'],.25)
        self.assertFalse(result['paired_statistical_evidence']['preregistered_sign_rule_met'])
        legacy=copy.deepcopy(record);legacy['identity'].pop('statistical_rule')
        with patch('vision_rsi.paired_study.load',return_value=legacy),patch('vision_rsi.paired_study.audit',side_effect=audited):
            old_result=compare(record['study_id'],self.studies)
        self.assertFalse(old_result['paired_statistical_evidence']['evaluated'])
        self.assertIn('Legacy',old_result['paired_statistical_evidence']['reason'])
        bound=identity['pairs'][0]['candidate'];path=self.campaigns/bound['session_id']/bound['campaign_id']/'state.json'
        original=path.read_text();state=json.loads(original);state['paused']=True;path.write_text(json.dumps(state))
        with patch('vision_rsi.paired_study.audit',side_effect=audited):paused=compare(record['study_id'],self.studies)
        self.assertFalse(paused['comparison_complete']);self.assertTrue(any('not settled' in row['error'] for row in paused['missing_evidence']))
        path.write_text(original)
        def stale(sid,*args):
            result=audited(sid,*args);result['campaign_state_sha256']='0'*64;return result
        with patch('vision_rsi.paired_study.audit',side_effect=stale):stale_result=compare(record['study_id'],self.studies)
        self.assertFalse(stale_result['comparison_complete'])
        self.assertTrue(all('changed during comparison' in row['error'] for row in stale_result['missing_evidence']))
        def changed(sid,*args):
            result=audited(sid,*args)
            if sid==identity['pairs'][0]['candidate']['session_id']:result['measurements'][0]['training_identity']['image_contents_sha256']='f'*64
            return result
        with patch('vision_rsi.paired_study.audit',side_effect=changed):result=compare(record['study_id'],self.studies)
        self.assertFalse(result['comparison_complete']);self.assertIsNone(result['mean_paired_ap_gain'])
