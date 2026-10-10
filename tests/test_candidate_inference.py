import copy
import unittest
from unittest.mock import patch

import test_candidate_serving as fixtures
from test_candidate_runtime import identity
from vision_rsi.candidate_inference import infer
from vision_rsi.candidate_serving import check
from vision_rsi.task_acceptance import accept
from vision_rsi.runner import digest


class CandidateInferenceTests(unittest.TestCase):
    setUp=fixtures.CandidateServingTests.setUp
    prepare=fixtures.CandidateServingTests.prepare
    registry=fixtures.CandidateServingTests.registry

    def ready(self,remote):
        development,_,sample=self.prepare(remote)
        registry,delivery=self.registry();base=remote.side_effect
        runtime=dict(identity(),protocol='vision-rsi/frozen-cpu-runtime/v2',userspace_sha256='c'*64,userspace_files=1,userspace_bytes=12)
        remote.side_effect=lambda *args:dict(base(*args),runtime_identity=runtime,runtime_identity_sha256=digest(runtime))
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        check(registry,self.session,delivery['version'],self.dataset,{},30)
        sample=copy.deepcopy(sample);sample['sample_id']='new-input'
        return registry,delivery,sample

    @patch('vision_rsi.remote.check_candidate')
    def test_single_batch_cache_and_changed_request_refused(self,remote):
        registry,delivery,sample=self.ready(remote)
        args=(registry,self.session,delivery['version'],'request-1',[sample],self.root,{})
        result=infer(*args)
        self.assertEqual(result['sample_ids'],['new-input']);self.assertEqual(remote.call_count,5)
        self.assertEqual(infer(*args),result);self.assertEqual(remote.call_count,5)
        second=dict(sample,sample_id='second')
        batch=infer(registry,self.session,delivery['version'],'request-2',[sample,second],self.root,{})
        self.assertEqual(len(batch['outputs']),2);self.assertFalse(batch['production_accepted'])
        with self.assertRaisesRegex(ValueError,'already bound'):infer(registry,self.session,delivery['version'],'request-1',[second],self.root,{})
        self.assertEqual(remote.call_count,6)

    @patch('vision_rsi.remote.check_candidate')
    def test_missing_serving_trial_never_dispatched(self,remote):
        registry,delivery,sample=self.ready(remote)
        (registry.root/self.session['task_id']/'candidate-serving/trial-1.json').unlink()
        with self.assertRaisesRegex(ValueError,'trial missing'):
            infer(registry,self.session,delivery['version'],'request-1',[sample],self.root,{})
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_inference_never_replayed(self,remote):
        registry,delivery,sample=self.ready(remote)
        args=(registry,self.session,delivery['version'],'request-1',[sample],self.root,{})
        remote.side_effect=RuntimeError('transport uncertain')
        with self.assertRaisesRegex(RuntimeError,'transport uncertain'):infer(*args)
        with self.assertRaisesRegex(RuntimeError,'Uncertain'):infer(*args)
        self.assertEqual(remote.call_count,5)

    @patch('vision_rsi.remote.check_candidate')
    def test_media_change_and_duplicate_ids_refused(self,remote):
        registry,delivery,sample=self.ready(remote)
        args=(registry,self.session,delivery['version'],'request-1',[sample],self.root,{})
        infer(*args)
        first=sample['inputs']['views']['items'][0]['uri'];(self.root/first).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'already bound'):infer(*args)
        with self.assertRaisesRegex(ValueError,'Duplicate'):infer(registry,self.session,delivery['version'],'request-2',[sample,sample],self.root,{})
        self.assertEqual(remote.call_count,5)

    @patch('vision_rsi.remote.check_candidate')
    def test_legacy_runtime_cannot_claim_frozen_inference(self,remote):
        development,_,sample=self.prepare(remote)
        registry,delivery=self.registry();base=remote.side_effect;runtime=identity()
        remote.side_effect=lambda *args:dict(base(*args),runtime_identity=runtime,runtime_identity_sha256=digest(runtime))
        accept(registry,self.session,delivery['version'],self.dataset,[development['execution_path']],{})
        check(registry,self.session,delivery['version'],self.dataset,{},30)
        with self.assertRaisesRegex(ValueError,'frozen userspace'):
            infer(registry,self.session,delivery['version'],'request-1',[sample],self.root,{})
        self.assertEqual(remote.call_count,4)
