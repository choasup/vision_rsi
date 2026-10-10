import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_adapter_evaluation as fixtures
from test_event_eval import event
from vision_rsi.bundle_evaluation import evaluate_bundle
from vision_rsi.candidate_bundle import build
from vision_rsi.capability import Capabilities
from vision_rsi.contracts import Sessions
from vision_rsi.controller import bind_validation, research_step
from vision_rsi.ledger import Ledger
from vision_rsi.research_history import inspect, accept
from vision_rsi.task_research import prepare, control


class ResearchHistoryTests(unittest.TestCase):
    setUp=fixtures.AdapterEvaluationTests.setUp

    @patch('vision_rsi.remote.check_candidate')
    def test_imported_baseline_history_is_not_covered_by_media_execution_receipts(self,remote):
        self.history(remote)
        self.ledger.append('external-baseline','evidence',{'summary':'Imported baseline','record_type':'baseline_binding','binding':{}})
        with self.assertRaisesRegex(ValueError,'baseline input history'):inspect(self.session,self.research_root)

    def test_compact_directory_checks_full_identity_on_collision(self):
        from vision_rsi.candidate_bundle import bound_directory
        with patch('vision_rsi.candidate_bundle.digest',return_value='a'*64):
            first=bound_directory(self.root/'artifacts',{'source':'one'})
            self.assertEqual(len(first.name),32)
            self.assertEqual(bound_directory(self.root/'artifacts',{'source':'one'}),first)
            with self.assertRaisesRegex(ValueError,'full identity differs'):
                bound_directory(self.root/'artifacts',{'source':'two'})

    def history(self, remote, runtime=None):
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[event(0,1)]} for _ in request['cases']]}}
        if runtime is not None:
            from vision_rsi.runner import digest
            base=remote.side_effect
            remote.side_effect=lambda *args:dict(base(*args),runtime_identity=runtime,runtime_identity_sha256=digest(runtime))
        sessions=Sessions(self.root/'sessions');session=sessions.create('history-fixture','Developer fixture')
        self.session=sessions.define(session['session_id'],json.loads(self.contract.read_text()))
        self.research_root=self.root/'research';prepared=prepare(self.session,self.research_root)
        self.folder=Path(prepared['directory']);self.ledger=Ledger(self.folder)
        samples=[]
        for split in ('development','holdout'):
            sample=json.loads(json.dumps(self.data['samples'][0]));sample['sample_id']=split
            for name,value in sample['inputs'].items():
                for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                    item['uri']=split+name+str(index)+'.bin';(self.folder/item['uri']).write_bytes(item['uri'].encode())
            samples.append(sample)
        dataset=self.folder/'development.json'
        def document(sample,purpose):
            return {'purpose':purpose,'samples':[sample],'ground_truth':{'labels':['action'],
                'samples':[{'sample_id':sample['sample_id'],'events':[event(0,1)]}]}}
        dataset.write_text(json.dumps(document(samples[0],'development_validation')))
        self.holdout=self.folder/'holdout.json';self.holdout.write_text(json.dumps(document(samples[1],'independent_acceptance')))
        bind_validation(self.ledger,{'research':{'task_contract':prepared['task_contract'],
            'validation_dataset':{'path':str(dataset),'sha256':hashlib.sha256(dataset.read_bytes()).hexdigest()},
            'candidate_bundle_execution':{'media_input':True,'decode_video':False}}})
        self.bundle=build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.folder/'contract.json',self.folder/'bundles',media_input=True)
        report=evaluate_bundle(self.bundle['path'],dataset,{},self.folder/'bundle-evaluations')
        self.report_path=Path(report['report_path'])
        self.ledger.append('evaluate','action',{'summary':'fixture evaluation','tool':'evaluate_contract','executor':'research-v1'})
        self.ledger.append('evaluate:result','result',{'summary':'measured fixture','action':'evaluate','status':'completed','observation':{
            'report_path':report['report_path'],'report_sha256':hashlib.sha256(self.report_path.read_bytes()).hexdigest(),
            'evaluation_identity':report['identity']}})
        self.ledger.append('pause','paused',{'summary':'development ended'})
        self.registry=Capabilities(self.root/'registry');self.addCleanup(self.registry.close)
        self.delivery=self.registry.register_candidate(self.session,self.bundle['path'])
        return report

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    @patch('vision_rsi.remote.check_candidate')
    def test_auto_history_seal_prevents_search_and_preserves_scope(self, remote, client):
        from test_candidate_runtime import identity
        self.history(remote,runtime=identity())
        history=inspect(self.session,self.research_root)
        self.assertEqual(len(history['development_paths']),1)
        self.assertFalse(history['complete_development_history_verified'])
        args=(self.registry,self.session,self.delivery['version'],self.holdout,{},self.research_root)
        result=accept(*args);self.assertEqual(accept(*args),result)
        self.assertTrue(result['research_history']['ledger_history_verified'])
        self.assertFalse(result['production_accepted']);self.assertEqual(remote.call_count,2)
        import subprocess
        import sys
        (self.root/'config.json').write_text(json.dumps({'remote':{}}))
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
            'training','accept-candidate','--from-research','--session-id',self.session['session_id'],
            '--version',self.delivery['version'],'--sessions','sessions','--research-root','research','--registry','registry',
            '--dataset',str(self.holdout),'--config','config.json','--json']
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        with self.assertRaisesRegex(ValueError,'sealed'):control(self.session,'resume',self.research_root)
        with self.assertRaisesRegex(ValueError,'sealed'):research_step({},self.folder)
        client.assert_not_called()

    @patch('vision_rsi.remote.check_candidate')
    def test_tampered_report_and_orphan_execution_refused(self, remote):
        report=self.history(remote);original=self.report_path.read_bytes()
        self.report_path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'report identity'):inspect(self.session,self.research_root)
        self.report_path.write_bytes(original)
        extra=self.folder/'bundle-evaluations'/'orphan';extra.mkdir();(extra/'execution.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unlinked'):inspect(self.session,self.research_root)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_pending_planning_and_uncovered_input_tools_refused(self, remote):
        self.history(remote)
        self.ledger.append('unknown-request','evidence',{'summary':'uncertain planner','record_type':'planning_request'})
        with self.assertRaisesRegex(ValueError,'unresolved planning'):inspect(self.session,self.research_root)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncovered_input_tool_refused_and_live_controller_lease_not_stolen(self, remote):
        from vision_rsi.campaign import lease
        self.history(remote)
        with lease(self.folder/'controller.lock',owner='live test controller'):
            with self.assertRaisesRegex(RuntimeError,'already active'):
                accept(self.registry,self.session,self.delivery['version'],self.holdout,{},self.research_root)
        self.assertFalse((self.folder/'acceptance-history.json').exists())
        self.ledger.append('resume','resumed',{'summary':'fixture resume'})
        self.ledger.append('read','action',{'summary':'input tool','tool':'check_contract','executor':'research-v1'})
        self.ledger.append('read:result','result',{'summary':'tool finished','action':'read','status':'completed'})
        self.ledger.append('pause2','paused',{'summary':'fixture pause'})
        with self.assertRaisesRegex(ValueError,'input-consuming'):inspect(self.session,self.research_root)

    @patch('vision_rsi.remote.check_candidate')
    def test_snapshot_changes_after_sealing_cannot_reuse_acceptance(self, remote):
        self.history(remote)
        args=(self.registry,self.session,self.delivery['version'],self.holdout,{},self.research_root)
        accept(*args)
        self.ledger.append('extra','evidence',{'summary':'external ledger mutation'})
        with self.assertRaisesRegex(ValueError,'already reserved'):accept(*args)
        self.assertEqual(remote.call_count,2)
