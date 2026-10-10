import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_research_history as fixtures
from test_candidate_runtime import identity
from vision_rsi.candidate_workflow import deliver,status,deliver_selected


class CandidateWorkflowTests(unittest.TestCase):
    @patch('vision_rsi.remote.check_candidate')
    def test_auto_selection_to_delivery_with_empty_registry_and_cli_restore(self,remote):
        self.prepared(remote)
        from vision_rsi.capability import Capabilities
        self.registry=Capabilities(self.root/'auto-registry');self.addCleanup(self.registry.close)
        self.assertEqual(self.registry.list(),[])
        args=(self.registry,self.session,self.holdout,self.research_root,{},30)
        result=deliver_selected(*args)
        self.assertEqual(result['status'],'scoped_delivery_ready_for_test')
        self.assertEqual(deliver_selected(*args),result)
        self.assertEqual(remote.call_count,4)
        (self.root/'config.json').write_text(json.dumps({'remote':{}}))
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'training','deliver-candidate','--select-development','--session-id',self.session['session_id'],
                 '--sessions',str(self.root/'sessions'),'--research-root',str(self.research_root),'--registry',str(self.registry.root),
                 '--dataset',str(self.holdout),'--max-latency-seconds','30','--config',str(self.root/'config.json')]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_selected_history_cannot_resume_or_append_before_acceptance(self,remote):
        self.prepared(remote)
        from vision_rsi.candidate_selection import select
        from vision_rsi.task_research import control
        from vision_rsi.controller import research_step
        select(self.registry,self.session,self.research_root)
        with self.assertRaisesRegex(ValueError,'selection sealed'):control(self.session,'resume',self.research_root)
        with self.assertRaisesRegex(ValueError,'selection sealed'):research_step({},self.folder)
        with self.assertRaisesRegex(ValueError,'selection sealed'):
            self.ledger.append('new-evidence','evidence',{'summary':'Unexpected new research evidence'})
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_interrupt_persists_phase_and_status_without_retry(self,remote):
        args=self.prepared(remote);base=remote.side_effect
        def interrupted(*values):
            if remote.call_count==3:raise KeyboardInterrupt()
            return base(*values)
        remote.side_effect=interrupted
        with self.assertRaises(KeyboardInterrupt):deliver(*args)
        observation=status(self.registry,self.session,self.delivery['version'])
        self.assertEqual(observation['workflow']['status'],'interrupted')
        self.assertEqual(observation['workflow']['stopped_phase'],'serving')
        self.assertFalse(observation['process_liveness_verified'])
        with self.assertRaisesRegex(RuntimeError,'uncertain'):deliver(*args)
        self.assertEqual(remote.call_count,3)

    @patch('vision_rsi.remote.check_candidate')
    def test_status_is_read_only_and_external_cli_does_not_require_config(self,remote):
        args=self.prepared(remote);deliver(*args)
        def snapshot():
            return {str(path):path.read_bytes() for path in self.registry.root.rglob('*') if path.is_file()}
        before=snapshot();observation=status(self.registry,self.session,self.delivery['version'])
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'training','delivery-status','--session-id',self.session['session_id'],
                 '--version',self.delivery['version'],'--sessions',str(self.root/'sessions'),'--registry',str(self.registry.root)]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),observation)
        self.assertEqual(before,snapshot())
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_status_rejects_changed_or_invalid_state(self,remote):
        from vision_rsi.runner import atomic_json,digest
        args=self.prepared(remote);deliver(*args)
        path=self.registry.root/self.session['task_id']/'delivery-workflows'/self.delivery['version']/'state.json'
        value=json.loads(path.read_text());value['status']='unknown-state'
        atomic_json(path,value)
        with self.assertRaisesRegex(ValueError,'integrity differs'):
            status(self.registry,self.session,self.delivery['version'])
        value['record_sha256']=digest({k:v for k,v in value.items() if k!='record_sha256'})
        atomic_json(path,value)
        with self.assertRaisesRegex(ValueError,'Invalid persisted'):
            status(self.registry,self.session,self.delivery['version'])
        self.assertEqual(remote.call_count,4)

    setUp=fixtures.ResearchHistoryTests.setUp
    history=fixtures.ResearchHistoryTests.history

    def prepared(self,remote):
        runtime=dict(identity(),protocol='vision-rsi/frozen-cpu-runtime/v2',userspace_sha256='c'*64,userspace_files=1,userspace_bytes=12)
        self.history(remote,runtime=runtime)
        return self.registry,self.session,self.delivery['version'],self.holdout,self.research_root,{},30

    @patch('vision_rsi.remote.check_candidate')
    def test_complete_restore_and_external_cli_use_same_version(self,remote):
        args=self.prepared(remote)
        result=deliver(*args)
        self.assertEqual(result['status'],'scoped_delivery_ready_for_test')
        self.assertEqual(result['completed_phases'],['acceptance','serving','promotion'])
        self.assertEqual(deliver(*args),result);self.assertEqual(remote.call_count,4)
        self.assertEqual(self.registry.resolve_version(self.session['task_id']),result['version'])
        (self.root/'config.json').write_text(json.dumps({'remote':{}}))
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'training','deliver-candidate','--session-id',self.session['session_id'],
                 '--version',self.delivery['version'],'--sessions',str(self.root/'sessions'),
                 '--research-root',str(self.research_root),'--registry',str(self.registry.root),
                 '--dataset',str(self.holdout),'--max-latency-seconds','30','--config',str(self.root/'config.json')]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_changed_target_refused_before_any_dispatch(self,remote):
        args=self.prepared(remote);deliver(*args)
        with self.assertRaisesRegex(ValueError,'already bound'):
            deliver(*args[:-1],60)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_serving_is_not_redispatched_on_restore(self,remote):
        args=self.prepared(remote);base=remote.side_effect
        def uncertain(*values):
            if remote.call_count==3:raise RuntimeError('lost serving connection')
            return base(*values)
        remote.side_effect=uncertain
        with self.assertRaisesRegex(RuntimeError,'lost serving'):deliver(*args)
        with self.assertRaisesRegex(RuntimeError,'uncertain'):deliver(*args)
        self.assertEqual(remote.call_count,3)
        path=self.registry.root/self.session['task_id']/'delivery-workflows'/self.delivery['version']/'state.json'
        state=json.loads(path.read_text())
        self.assertEqual(state['status'],'stopped');self.assertEqual(state['stopped_phase'],'serving')
        self.assertEqual(state['completed_phases'],['acceptance'])

    @patch('vision_rsi.remote.check_candidate')
    def test_invalid_latency_does_not_consume_acceptance(self,remote):
        args=self.prepared(remote)
        with self.assertRaisesRegex(ValueError,'finite latency'):deliver(*args[:-1],float('nan'))
        self.assertEqual(remote.call_count,1)
        self.assertFalse((self.registry.root/self.session['task_id']/'candidate-acceptance').exists())

    @patch('vision_rsi.remote.check_candidate')
    def test_failed_holdout_stops_before_serving_or_promotion(self,remote):
        args=self.prepared(remote);base=remote.side_effect
        def missed(*values):
            result=base(*values)
            result['observation']['results']=[{'events':[]} for _ in values[1]['cases']]
            return result
        remote.side_effect=missed
        result=deliver(*args)
        self.assertEqual(result['status'],'acceptance_not_met')
        self.assertEqual(result['completed_phases'],['acceptance'])
        self.assertEqual(deliver(*args),result)
        self.assertEqual(remote.call_count,2)
        self.assertFalse((self.registry.root/self.session['task_id']/'candidate-serving').exists())
        with self.assertRaisesRegex(ValueError,'No validated'):
            self.registry.resolve_version(self.session['task_id'])
