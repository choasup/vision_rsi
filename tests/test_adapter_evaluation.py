import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.adapter_evaluation import evaluate
from vision_rsi.candidates import Candidates,git
import test_event_eval as fixtures
from test_event_eval import event


class AdapterEvaluationTests(unittest.TestCase):
    def test_task_bound_candidate_registration_is_stable_and_never_test_ready(self):
        from vision_rsi.candidate_bundle import build
        from vision_rsi.capability import Capabilities
        contract=json.loads(self.contract.read_text())
        session={'session_id':'a'*32,'task_id':'video-task','versions':[{'contract':contract}]}
        bundle=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles')
        registry=Capabilities(self.root/'registry');self.addCleanup(registry.close)
        manifest=registry.register_candidate(session,bundle['path'])
        self.assertEqual(manifest['status'],'pending_independent_validation')
        self.assertEqual(registry.register_candidate(session,bundle['path']),manifest)
        self.assertEqual(len(registry.list()),1)
        with self.assertRaisesRegex(ValueError,'No validated'):registry.resolve_version('video-task',manifest['version'])
        changed=dict(session,versions=[{'contract':dict(contract,goal='changed task')}])
        with self.assertRaisesRegex(ValueError,'contract differs'):registry.register_candidate(changed,bundle['path'])
        with self.assertRaisesRegex(ValueError,'Resolve task'):registry.register_candidate(dict(session,pending_request='pending'),bundle['path'])
        artifact=registry.root/'video-task'/manifest['version']/'bundle.json';artifact.write_text('{}')
        with self.assertRaisesRegex(ValueError,'artifact changed'):registry.register_candidate(session,bundle['path'])

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_controller_evaluates_frozen_media_bundle_mode(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        sample=self.data['samples'][0]
        for field,value in sample['inputs'].items():
            for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                name=field+str(index)+'.bin';item['uri']=name;(self.root/name).write_bytes(name.encode())
        self.dataset.write_text(json.dumps(self.data),encoding='utf-8')
        ledger=Ledger(self.root);ledger.append('objective','objective',{'summary':'media research'})
        ledger.append('stage','action',{'summary':'stage','tool':'stage_candidate','executor':'research-v1'})
        ledger.append('stage:result','result',{'summary':'candidate','action':'stage','status':'completed','observation':{'candidate_id':self.candidate}})
        config={'llm':{'model':'fixture'},'remote':{},'research':{'allow_candidate_checks':True,
            'candidate_bundle_execution':{'media_input':True,'decode_video':False},
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'evaluate_contract','summary':'measure',
            'question':'q','expected_evidence':'media metric','refs':['stage:result'],
            'arguments':{'candidate_id':self.candidate,'module':'vision_rsi.adapter_fixture','function':'predict'}})}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        research_step(config,self.root,repository=self.store.repository)
        result=ledger.events()[-1]['payload'];self.assertEqual(result['status'],'completed')
        self.assertEqual(result['observation']['metric_report']['event_micro_f1'],0)
        self.assertTrue(result['observation']['acceptance_evaluated'])
        self.assertEqual(result['observation']['evaluation_identity']['module'],'vision_rsi.adapter_fixture')
        self.assertIn('media',remote.call_args.args[1]['cases'][0])
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertEqual(prompt['candidate_bundle_execution'],config['research']['candidate_bundle_execution'])
        config['research']['candidate_bundle_execution']['media_input']=False
        with self.assertRaisesRegex(ValueError,'binding is frozen'):research_step(config,self.root,repository=self.store.repository)
        self.assertEqual(client.return_value.complete.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_bundle_metrics_bind_actual_media_and_keep_ground_truth_local(self,remote):
        from vision_rsi.candidate_bundle import build
        from vision_rsi.bundle_evaluation import evaluate_bundle
        sample=self.data['samples'][0]
        for field,value in sample['inputs'].items():
            items=value['items'] if value['type']=='image_list' else [value]
            for index,item in enumerate(items):
                name=field+str(index)+'.bin';item['uri']=name;(self.root/name).write_bytes(name.encode())
        self.dataset.write_text(json.dumps(self.data),encoding='utf-8')
        bundle=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles',True)
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        first=evaluate_bundle(bundle['path'],self.dataset,{},self.root/'evaluations')
        self.assertEqual(first['metric_report']['event_micro_f1'],0)
        self.assertFalse(first['production_accepted'])
        self.assertNotIn('ground_truth',json.dumps(remote.call_args.args[1]))
        self.assertEqual(evaluate_bundle(bundle['path'],self.dataset,{},self.root/'evaluations'),first)
        self.assertEqual(remote.call_count,1)
        (self.root/'views0.bin').write_bytes(b'changed media')
        second=evaluate_bundle(bundle['path'],self.dataset,{},self.root/'evaluations')
        self.assertNotEqual(first['identity']['execution_record_sha256'],second['identity']['execution_record_sha256'])
        self.assertNotEqual(first['report_path'],second['report_path'])
        self.assertEqual(remote.call_count,2)
        self.dataset.write_text(json.dumps(dict(self.data,purpose='hidden_test')),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'no hidden-test'):evaluate_bundle(bundle['path'],self.dataset,{},self.root/'evaluations')
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_media_bundle_transports_joint_bytes_and_changed_content_changes_execution(self,remote):
        import base64
        from vision_rsi.candidate_bundle import build,run
        contract=json.loads(self.contract.read_text());sample=json.loads(json.dumps(contract['example_input']))
        for field,value in sample['inputs'].items():
            items=value['items'] if value['type']=='image_list' else [value]
            for index,item in enumerate(items):
                if 'uri' in item:
                    name=field+str(index)+'.bin';item['uri']=name;(self.root/name).write_bytes((field+str(index)).encode())
        bundle=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles',media_input=True)
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        with self.assertRaisesRegex(ValueError,'base directory'):run(bundle['path'],[sample],{},self.root/'executions')
        first=run(bundle['path'],[sample],{},self.root/'executions',media_directory=self.root)
        packet=remote.call_args.args[1]['cases'][0]['media']
        self.assertEqual(len(packet['assets']),3)
        self.assertEqual(first['input_manifest'][0]['media_sha256'],[asset['sha256'] for asset in packet['assets']])
        self.assertTrue(first['input_manifest'][0]['media_coverage_complete'])
        self.assertEqual(run(bundle['path'],[sample],{},self.root/'executions',media_directory=self.root),first)
        self.assertFalse(packet['media_decoded'])
        for asset in packet['assets']:
            uri=sample['inputs'][asset['field']]
            uri=uri['items'][asset['index']]['uri'] if uri['type']=='image_list' else uri['uri']
            self.assertEqual(base64.b64decode(asset['content_base64']),(self.root/uri).read_bytes())
        changed=self.root/sample['inputs']['views']['items'][0]['uri'];changed.write_bytes(b'new bytes')
        second=run(bundle['path'],[sample],{},self.root/'executions',media_directory=self.root)
        self.assertNotEqual(first['binding']['request_sha256'],second['binding']['request_sha256'])
        self.assertNotEqual(first['input_manifest'][0]['input_content_sha256'],second['input_manifest'][0]['input_content_sha256'])
        self.assertEqual(remote.call_count,2)
        changed.write_bytes(b'x'*(512*1024+1))
        with self.assertRaises(ValueError):run(bundle['path'],[sample],{},self.root/'executions',media_directory=self.root)
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_portable_bundle_runs_single_and_batch_without_git_store(self,remote):
        from vision_rsi.candidate_bundle import build,run
        bundle=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles')
        sample=self.data['samples'][0]
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]} for case in request['cases']]}}
        copied=self.root/'portable.json';copied.write_bytes(Path(bundle['path']).read_bytes())
        result=run(copied,[sample],{},self.root/'executions',bundle['bundle_id'])
        self.assertEqual(result['outputs'],[{'events':[]}]);self.assertFalse(result['quality_verified'])
        self.assertEqual(run(copied,[sample],{},self.root/'executions',bundle['bundle_id']),result)
        self.assertEqual(remote.call_count,1)
        batch=run(copied,[sample,dict(sample,sample_id='clip2')],{},self.root/'executions')
        self.assertEqual(len(batch['outputs']),2);self.assertEqual(remote.call_count,2)
        with self.assertRaisesRegex(ValueError,'Pinned bundle'):run(copied,[sample],{},self.root/'executions','0'*64)
        remote.side_effect=RuntimeError('transport outcome unknown')
        sample=dict(sample,sample_id='uncertain')
        with self.assertRaisesRegex(RuntimeError,'transport'):run(copied,[sample],{},self.root/'executions')
        with self.assertRaisesRegex(RuntimeError,'Uncertain bundle'):run(copied,[sample],{},self.root/'executions')
        self.assertEqual(remote.call_count,3)

    def test_candidate_bundle_is_portable_and_refuses_changed_existing_bytes(self):
        from vision_rsi.candidate_bundle import build,verify
        result=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles')
        self.assertFalse(result['production_accepted']);self.assertFalse(result['capability_registered'])
        original=Path(result['path']).read_bytes()
        copied=self.root/'independent-bundle.json';copied.write_bytes(original)
        self.assertEqual(verify(copied)['bundle_id'],result['bundle_id'])
        self.assertEqual(build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles'),result)
        broken=json.loads(original);broken['files']['vision_rsi/adapter_fixture.py']='Yg=='
        Path(result['path']).write_text(json.dumps(broken),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source hash mismatch'):verify(result['path'])
        with self.assertRaises(ValueError):build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles')
        self.assertEqual(json.loads(Path(result['path']).read_text()),broken)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_controller_reads_bound_candidate_source_after_old_history_window(self,client):
        from vision_rsi.controller import research_step,observation_context
        from vision_rsi.ledger import Ledger
        parent=json.loads((self.store.root/self.candidate/'candidate.json').read_text())
        ledger=Ledger(self.root);ledger.append('objective','objective',{'summary':'read earlier candidate'})
        ledger.append('stage','action',{'summary':'stage','tool':'stage_candidate','executor':'research-v1'})
        ledger.append('stage:result','result',{'summary':'staged','action':'stage','status':'completed','observation':parent})
        for i in range(20):ledger.append('noise'+str(i),'evidence',{'summary':'later observation'})
        args={'candidate_id':self.candidate,'path':'vision_rsi/adapter_fixture.py',
              'expected_sha256':parent['source_hashes']['vision_rsi/adapter_fixture.py'],'start_line':1,'max_lines':100}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'read_candidate_source','summary':'read',
            'question':'q','expected_evidence':'source','refs':['stage:result'],'arguments':args})}
        research_step({'llm':{'model':'fixture'}},self.root,repository=self.store.repository)
        result=ledger.events()[-1]['payload']
        self.assertEqual(result['status'],'completed');self.assertTrue(result['read_only'])
        self.assertIn('def predict',result['observation']['source_excerpt'])
        self.assertEqual(observation_context(result['observation'])['candidate_id'],self.candidate)
        from vision_rsi.controller import execute
        config={'_research_candidate_context':{'store':str(self.store.root)}}
        restored=execute('read_candidate_source',config,self.store.repository,{key:value for key,value in args.items() if key!='expected_sha256'})
        self.assertEqual(restored['source_sha256'],args['expected_sha256'])
        with self.assertRaisesRegex(ValueError,'hash was not observed'):
            execute('read_candidate_source',config,self.store.repository,dict(args,expected_sha256='0'*64))

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_controller_failed_metric_to_child_reevaluation(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        from vision_rsi.research_memory import metric_memory
        ledger=Ledger(self.root);ledger.append('objective','objective',{'summary':'fixture iterative development'})
        parent=json.loads((self.store.root/self.candidate/'candidate.json').read_text())
        for key,tool,observation in [('inspect','inspect_repository',{'git_revision':git(self.store.repository,'rev-parse','HEAD')}),
                                     ('parent','stage_candidate',dict(parent,base_revision=parent['identity']['base_revision']))]:
            ledger.append(key,'action',{'summary':key,'executor':'research-v1','tool':tool})
            ledger.append(key+':result','result',{'summary':key,'action':key,'status':'completed','observation':observation})
        config={'llm':{'model':'fixture'},'remote':{},'research':{'allow_candidate_writes':True,'allow_candidate_checks':True,
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        proposal={'hypothesis':'fixture correction','expected_improvement':'fixed validation F1','evaluation_plan':'same dataset',
                  'edits':[{'path':'vision_rsi/adapter_fixture.py','base_sha256':parent['source_hashes']['vision_rsi/adapter_fixture.py'],
                            'content':'def predict(sample):\n    return {"events": [{"label":"action","start_seconds":0,"end_seconds":1}]}\n'}]}
        prompts=[]
        def plan(messages,**kwargs):
            prompt=json.loads(messages[0]['content']);prompts.append(prompt)
            if len(prompts)==2:
                self.assertEqual(prompt['candidate_metric_memory']['groups'][0]['latest_failure']['event_micro_f1'],0)
                value={'tool':'stage_candidate','refs':['parent:result'],
                       'arguments':{'parent_candidate_id':self.candidate,'base_revision':parent['git_revision'],'proposal':proposal}}
            else:
                staged=[e for e in ledger.events() if e['kind']=='result' and e['payload'].get('observation',{}).get('git_revision')]
                latest=staged[-1]
                value={'tool':'evaluate_contract','refs':[latest['key']],
                       'arguments':{'candidate_id':latest['payload']['observation']['candidate_id'],
                                    'module':'vision_rsi.adapter_fixture','function':'predict'}}
            return {'content':json.dumps(dict(value,summary='fixture action',question='q',expected_evidence='measured fixture'))}
        client.return_value.complete.side_effect=plan
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'observation':{'results':[{'events':[] if request['source_hashes']['vision_rsi/adapter_fixture.py']==parent['source_hashes']['vision_rsi/adapter_fixture.py'] else [event(0,1)]}]}}
        research_step(config,self.root,steps=3,repository=self.store.repository)
        memory=metric_memory(ledger.events());group=memory['groups'][0]
        self.assertEqual(memory['evaluation_count'],2)
        self.assertEqual(memory['comparison_group_count'],1)
        self.assertEqual(group['best']['event_micro_f1'],1)
        self.assertEqual(group['latest_failure']['event_micro_f1'],0)
        self.assertNotEqual(group['best']['candidate_id'],self.candidate)
        self.assertEqual(remote.call_count,2)
        self.assertEqual(client.return_value.complete.call_count,3)

    def test_child_candidate_inherits_parent_and_keeps_main_unchanged(self):
        from vision_rsi.controller import execute
        parent=json.loads((self.store.root/self.candidate/'candidate.json').read_text())
        name='vision_rsi/adapter_fixture.py'
        proposal={'hypothesis':'repair failed metric','expected_improvement':'testable','evaluation_plan':'fixed validation',
                  'edits':[{'path':name,'base_sha256':parent['source_hashes'][name],
                            'content':'def predict(sample):\n    return {"events": [{"label":"action","start_seconds":0,"end_seconds":1}]}\n'}]}
        args={'base_revision':parent['git_revision'],'parent_candidate_id':self.candidate,'proposal':proposal}
        config={'research':{'allow_candidate_writes':True},'_research_candidate_context':{
            'store':str(self.store.root),'binding':{'action_key':'repair','objective_sha256':'a'*64}}}
        main_before=git(self.store.repository,'rev-parse','HEAD')
        result=execute('stage_candidate',config,self.store.repository,args)
        child=json.loads((self.store.root/result['candidate_id']/'candidate.json').read_text())
        self.assertEqual(child['identity']['context']['parent_candidate_id'],self.candidate)
        self.assertEqual(git(child['checkout'],'rev-parse','HEAD^'),parent['git_revision'])
        self.assertEqual(git(self.store.repository,'rev-parse','HEAD'),main_before)
        self.assertEqual(execute('stage_candidate',config,self.store.repository,args)['candidate_id'],result['candidate_id'])
        with self.assertRaisesRegex(ValueError,'revision changed'):
            execute('stage_candidate',config,self.store.repository,dict(args,base_revision=main_before))
        extra=dict(proposal,edits=[{'path':'vision_rsi/harness_helper.py','base_sha256':None,'content':'VALUE = 1\n'}])
        next_args={'base_revision':child['git_revision'],'parent_candidate_id':child['candidate_id'],'proposal':extra}
        grandchild=execute('stage_candidate',config,self.store.repository,next_args)
        with patch('vision_rsi.remote.check_candidate') as remote:
            remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],'observation':{}}
            self.store.check(grandchild['candidate_id'],{},'vision_rsi.adapter_fixture','predict',[{'sample':{}}])
            self.assertIn(name,remote.call_args.args[1]['files'])
            self.assertIn('vision_rsi/harness_helper.py',remote.call_args.args[1]['files'])

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_detection_contract_does_not_offer_event_metric_tool(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        contract=json.loads(self.contract.read_text())
        contract['acceptance']={'metric':'box_AP','direction':'maximize','threshold':60,
                                'evaluation_protocol':'coco_bbox'}
        self.contract.write_text(json.dumps(contract),encoding='utf-8')
        ledger=Ledger(self.root/'detection-ledger')
        ledger.append('objective','objective',{'summary':'detection task'})
        ledger.append('stage','action',{'summary':'staged','executor':'research-v1','tool':'stage_candidate'})
        ledger.append('stage:result','result',{'summary':'candidate','action':'stage','status':'completed',
                      'observation':{'candidate_id':self.candidate}})
        config={'llm':{'model':'fixture'},'research':{'allow_candidate_checks':True,
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'evaluate_contract','summary':'invalid protocol',
            'question':'q','expected_evidence':'metric','refs':['stage:result'],
            'arguments':{'candidate_id':self.candidate,'module':'vision_rsi.adapter_fixture','function':'predict'}})}
        research_step(config,ledger.directory,steps=1)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertNotIn('evaluate_contract',prompt['available_tools'])
        self.assertNotIn('evaluate_contract',prompt['tools'])
        remote.assert_not_called()
        self.assertFalse(any(e['kind']=='action' and e['payload'].get('tool')=='evaluate_contract' for e in ledger.events()))

    def test_validation_binding_cannot_change_or_disappear_between_steps(self):
        from vision_rsi.controller import bind_validation
        from vision_rsi.ledger import Ledger
        ledger=Ledger(self.root/'binding-ledger')
        ledger.append('objective','objective',{'summary':'fixed development experiment'})
        config={'research':{'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
                          'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        bind_validation(ledger,config);bind_validation(ledger,config)
        self.assertEqual(len(ledger.events()),2)
        with self.assertRaisesRegex(ValueError,'cannot be removed'):bind_validation(ledger,{})
        self.dataset.write_text(json.dumps(dict(self.data,purpose='other')),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'changed before planning'):bind_validation(ledger,config)
        config['research']['validation_dataset']['sha256']=hashlib.sha256(self.dataset.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'binding is frozen'):bind_validation(ledger,config)

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_controller_can_evaluate_only_a_staged_candidate_on_configured_data(self,remote,client):
        from vision_rsi.controller import research_step
        from vision_rsi.ledger import Ledger
        ledger=Ledger(self.root)
        ledger.append('goal','objective',{'summary':'Fixture candidate metric investigation'})
        ledger.append('stage','action',{'summary':'staged fixture','tool':'stage_candidate','executor':'research-v1'})
        ledger.append('stage:result','result',{'summary':'staged','action':'stage','status':'completed',
                      'observation':{'candidate_id':self.candidate}})
        config={'llm':{'model':'fixture'},'remote':{},'research':{'allow_candidate_checks':True,
            'task_contract':{'path':str(self.contract),'sha256':hashlib.sha256(self.contract.read_bytes()).hexdigest()},
            'validation_dataset':{'path':str(self.dataset),'sha256':hashlib.sha256(self.dataset.read_bytes()).hexdigest()}}}
        client.return_value.complete.return_value={'content':json.dumps({'tool':'evaluate_contract','summary':'measure',
            'question':'q','expected_evidence':'fixed F1','refs':['stage:result'],
            'arguments':{'candidate_id':self.candidate,'module':'vision_rsi.adapter_fixture','function':'predict'}})}
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[]}]}}
        research_step(config,self.root,steps=1,repository=self.store.repository)
        result=ledger.events()[-1]['payload']
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['observation']['runtime_status'],'development_metric_not_met')
        self.assertEqual(result['observation']['metric_report']['event_micro_f1'],0)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertIn('evaluate_contract',prompt['available_tools'])
        self.assertEqual(prompt['validation_dataset']['sha256'],config['research']['validation_dataset']['sha256'])
        self.assertNotIn('ground_truth',remote.call_args.args[1])
        # The next persisted planner request must receive numeric failures as
        # structured evidence, rather than a potentially truncated JSON excerpt.
        client.return_value.complete.return_value={'content':json.dumps({'tool':'inspect_repository','summary':'inspect',
            'question':'q','expected_evidence':'source','refs':[]})}
        research_step(config,self.root,steps=1,repository=self.store.repository)
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        metrics=[row['observation'] for row in prompt['history']
                 if row['observation'].get('kind')=='candidate_development_metric']
        self.assertEqual(len(metrics),1)
        self.assertEqual(metrics[0]['metric_report']['event_micro_f1'],0)
        self.assertFalse(metrics[0]['metric_report']['metric_threshold_met'])
        self.assertEqual(metrics[0]['metric_report']['error_analysis']['worst_labels'][0]['fn'],1)
        self.assertEqual(metrics[0]['metric_report']['error_analysis']['worst_samples'][0]['fn'],1)
        self.assertFalse(metrics[0]['production_acceptance_verified'])
        self.assertEqual(prompt['candidate_metric_memory']['evaluation_count'],1)
        self.assertEqual(prompt['candidate_metric_memory']['groups'][0]['best']['event_micro_f1'],0)

    @patch('vision_rsi.remote.check_candidate')
    def test_configured_dataset_hash_mismatch_refuses_remote(self,remote):
        with self.assertRaisesRegex(ValueError,'dataset changed'):
            evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset,
                     expected_dataset_sha256='0'*64)
        remote.assert_not_called()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);repo=self.root/'repo';repo.mkdir()
        git(repo,'init');(repo/'vision_rsi').mkdir();(repo/'vision_rsi/research.py').write_text('# fixture\n')
        git(repo,'add','.');git(repo,'-c','user.name=Fixture','-c','user.email=fixture@local.invalid','commit','-m','base')
        self.store=Candidates(self.root/'candidates',repo);self.addCleanup(self.store.close)
        proposal={'hypothesis':'fixture metric pipeline','expected_improvement':'testable','evaluation_plan':'development validation',
                  'edits':[{'path':'vision_rsi/adapter_fixture.py','base_sha256':None,'content':'def predict(sample):\n    return {"events": []}\n'}]}
        self.candidate=self.store.create(proposal,{'fixture':True})['candidate_id']
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
        metric_contract=fixtures.EventEvaluationTests.contract(None)
        contract.update(acceptance=metric_contract['acceptance'],output_schema=metric_contract['output_schema'],example_output={'events':[]})
        self.contract=self.root/'contract.json';self.contract.write_text(json.dumps(contract),encoding='utf-8')
        sample=dict(contract['example_input'],sample_id='clip1')
        self.dataset=self.root/'validation.json'
        self.data={'purpose':'development_validation','samples':[sample],
                   'ground_truth':{'labels':['action'],'samples':[{'sample_id':'clip1','events':[event(0,1)]}]}}
        self.dataset.write_text(json.dumps(self.data),encoding='utf-8')

    @patch('vision_rsi.remote.check_candidate')
    def test_interface_pass_with_wrong_output_fails_metric_and_reuses_runtime(self,remote):
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[]}]}}
        result=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result['status'],'development_metric_not_met')
        self.assertEqual(result['metric_report']['event_micro_f1'],0)
        self.assertFalse(result['quality_verified']);self.assertFalse(result['agent_adopted'])
        repeated=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result,repeated)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_metric_met_is_not_production_acceptance_or_adoption(self,remote):
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
                                                     'observation':{'results':[{'events':[event(0,1)]}]}}
        result=evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        self.assertEqual(result['status'],'development_metric_met')
        self.assertEqual(result['metric_report']['event_micro_f1'],1)
        self.assertFalse(result['quality_verified']);self.assertFalse(result['capability_registered'])
        self.assertNotIn('ground_truth',json.dumps(remote.call_args.args[1]))

    @patch('vision_rsi.remote.check_candidate')
    def test_dataset_scope_and_coverage_refuse_execution(self,remote):
        for changed in (dict(self.data,purpose='hidden_test'),dict(self.data,ground_truth={'labels':['action'],'samples':[]})):
            self.dataset.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(ValueError):evaluate(self.store,self.candidate,{},'vision_rsi.adapter_fixture','predict',self.contract,self.dataset)
        remote.assert_not_called()
