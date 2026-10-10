import json
import unittest
from unittest.mock import patch

import test_bundle_acceptance as fixtures
from vision_rsi.capability import Capabilities
from vision_rsi.candidate_bundle import build
from vision_rsi.task_acceptance import accept, status


class TaskAcceptanceTests(unittest.TestCase):
    setUp = fixtures.BundleAcceptanceTests.setUp
    prepare = fixtures.BundleAcceptanceTests.prepare

    def registry(self):
        registry=Capabilities(self.root/'registry');self.addCleanup(registry.close)
        self.session={'session_id':'a'*32,'task_id':'task-fixture',
                      'versions':[{'contract':json.loads(self.contract.read_text())}]}
        delivery=registry.register_candidate(self.session,self.bundle['path'])
        return registry,delivery

    @patch('vision_rsi.remote.check_candidate')
    def test_task_slot_persists_reuses_evidence_and_does_not_promote(self, remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        values=(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        result=accept(*values)
        self.assertEqual(status(registry,'task-fixture')['status'],'completed')
        self.assertEqual(accept(*values),result);self.assertEqual(remote.call_count,2)
        self.assertFalse(result['production_accepted'])
        self.assertEqual(registry.list()[0]['status'],'pending_independent_validation')
        with self.assertRaisesRegex(ValueError,'No validated'):registry.resolve_version('task-fixture')
        second=Capabilities(registry.root)
        try:
            self.assertEqual(status(second,'task-fixture')['report_sha256'],result['report_sha256'])
            self.assertEqual(accept(second,*values[1:]),result)
        finally:second.close()

    @patch('vision_rsi.remote.check_candidate')
    def test_new_candidate_dataset_and_session_cannot_reset_task_slot(self, remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        other=build(self.store,self.candidate,'vision_rsi.adapter_fixture','other_predict',self.contract,self.root/'bundles',media_input=True)
        next_version=registry.register_candidate(self.session,other['path'])['version']
        with self.assertRaisesRegex(ValueError,'already reserved'):
            accept(registry,self.session,next_version,self.dataset,[development['execution_path']],{})
        session=dict(self.session,session_id='b'*32)
        next_version=registry.register_candidate(session,self.bundle['path'])['version']
        with self.assertRaisesRegex(ValueError,'already reserved'):
            accept(registry,session,next_version,self.dataset,[development['execution_path']],{})
        self.dataset.write_text(self.dataset.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'already reserved'):
            accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_remote_keeps_reservation_across_process_restart(self, remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        remote.side_effect=RuntimeError('connection lost')
        values=(self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        with self.assertRaisesRegex(RuntimeError,'connection lost'):accept(registry,*values)
        self.assertEqual(status(registry,'task-fixture')['status'],'reserved')
        second=Capabilities(registry.root)
        try:
            with self.assertRaisesRegex(RuntimeError,'Uncertain'):accept(second,*values)
        finally:second.close()
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_stale_requirements_and_corrupt_artifact_refused(self, remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        values=(delivery['version'],self.dataset,[development['execution_path']],{})
        with self.assertRaisesRegex(ValueError,'Resolve task'):
            accept(registry,dict(self.session,pending_request=True),*values)
        changed=dict(self.session,versions=self.session['versions']*2)
        with self.assertRaisesRegex(ValueError,'another task contract'):
            accept(registry,changed,*values)
        folder=registry.root/'task-fixture'/delivery['version'];(folder/'bundle.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'artifact integrity'):accept(registry,self.session,*values)
        self.assertEqual(status(registry,'task-fixture')['status'],'not_reserved')
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_competing_dataset_reservations_admit_only_one(self, remote):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        alternate=self.root/'alternate.json';alternate.write_text(self.dataset.read_text()+'\n')
        barrier=Barrier(2)
        def reserve(path):
            local=Capabilities(registry.root)
            try:
                barrier.wait(timeout=10)
                try:
                    return accept(local,self.session,delivery['version'],path,[development['execution_path']],{})
                except ValueError as error:return str(error)
            finally:local.close()
        with patch('vision_rsi.bundle_acceptance.accept',return_value={'report_sha256':'f'*64}) as gate:
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,[self.dataset,alternate]))
        self.assertEqual(sum(isinstance(result,dict) for result in results),1)
        self.assertTrue(any('already reserved' in result for result in results if isinstance(result,str)))
        self.assertEqual(gate.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_invalid_dataset_does_not_consume_slot(self, remote):
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        self.data['ground_truth']['samples'][0]['events'][0]['label']='unknown'
        self.dataset.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        self.assertEqual(status(registry,'task-fixture')['status'],'not_reserved')
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_post_reservation_file_change_refused_before_remote(self, remote):
        import vision_rsi.bundle_acceptance as evaluator
        development,_,_=self.prepare(remote);registry,delivery=self.registry()
        original=evaluator.accept
        def changed(*args,**kwargs):
            self.dataset.write_text(self.dataset.read_text()+'\n')
            return original(*args,**kwargs)
        with patch('vision_rsi.bundle_acceptance.accept',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'content changed before execution'):
                accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        self.assertEqual(status(registry,'task-fixture')['status'],'reserved')
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_actual_cli_cached_result_and_status_use_caller_paths(self, remote):
        import subprocess
        import sys
        from pathlib import Path
        from vision_rsi.contracts import Sessions
        development,_,_=self.prepare(remote)
        sessions=Sessions(self.root/'sessions');session=sessions.create('cli-fixture','Developer fixture')
        session=sessions.define(session['session_id'],json.loads(self.contract.read_text()))
        registry=Capabilities(self.root/'registry');self.addCleanup(registry.close)
        delivery=registry.register_candidate(session,self.bundle['path'])
        result=accept(registry,session,delivery['version'],self.dataset,[development['execution_path']],{})
        (self.root/'config.json').write_text(json.dumps({'remote':{}}))
        launcher=Path(__file__).resolve().parents[1]/'launch_agent.py'
        command=[sys.executable,'-X','utf8',str(launcher),'--cli','training','accept-candidate',
                 '--session-id',session['session_id'],'--sessions','sessions','--registry','registry','--version',delivery['version'],
                 '--dataset',self.dataset.name,'--development',development['execution_path'],'--config','config.json','--json']
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        before=(registry.root/'registry.sqlite3').read_bytes()
        command=[sys.executable,'-X','utf8',str(launcher),'--cli','training','candidate-acceptance-status',
                 '--session-id',session['session_id'],'--sessions','sessions','--registry','registry','--json']
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'],'completed')
        self.assertEqual((registry.root/'registry.sqlite3').read_bytes(),before)
        self.assertEqual(remote.call_count,2)
