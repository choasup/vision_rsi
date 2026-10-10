import unittest
from unittest.mock import patch

import test_candidate_delivery as fixtures
from vision_rsi.release_status import inspect


class CandidateReleaseStatusTests(unittest.TestCase):
    setUp=fixtures.CandidateDeliveryTests.setUp
    history=fixtures.CandidateDeliveryTests.history
    ready=fixtures.CandidateDeliveryTests.ready

    def snapshot(self):
        return {str(path.relative_to(self.root)):path.read_bytes()
                for folder in (self.registry.root,self.research_root,self.root/'sessions')
                for path in folder.rglob('*') if path.is_file()}

    @patch('vision_rsi.remote.check_candidate')
    def test_candidate_release_status_is_read_only_and_scoped(self,remote):
        delivery=self.ready(remote)
        lock=self.registry.root/self.session['task_id']/'candidate-serving/serving.lock'
        lock.unlink()
        before=self.snapshot()
        result=inspect(self.session['session_id'],self.root/'sessions',self.registry.root)
        self.assertTrue(result['local_release_evidence_complete'],result)
        self.assertEqual(result['status'],'local_evidence_ready_for_test')
        self.assertEqual(result['versions'][0]['version'],delivery['version'])
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['complete_development_history_verified'])
        self.assertFalse(result['remote_availability_verified'])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_missing_trial_is_not_repaired_or_dispatched(self,remote):
        self.ready(remote)
        (self.registry.root/self.session['task_id']/'candidate-serving/trial-1.json').unlink()
        before=self.snapshot()
        result=inspect(self.session['session_id'],self.root/'sessions',self.registry.root)
        self.assertFalse(result['local_release_evidence_complete'])
        self.assertIn('trial missing',result['versions'][0]['blocker'])
        self.assertEqual(before,self.snapshot())
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_changed_live_requirements_do_not_reuse_old_delivery(self,remote):
        from vision_rsi.contracts import Sessions
        import copy
        self.ready(remote)
        contract=copy.deepcopy(self.session['versions'][-1]['contract']);contract['goal']='New requirements'
        Sessions(self.root/'sessions').define(self.session['session_id'],contract)
        result=inspect(self.session['session_id'],self.root/'sessions',self.registry.root)
        self.assertFalse(result['local_release_evidence_complete'])
        self.assertIn('current task',result['versions'][0]['blocker'])
        self.assertEqual(remote.call_count,4)
