import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_adapter_evaluation as fixtures
from test_event_eval import event
from vision_rsi.candidate_bundle import build, run
from vision_rsi.bundle_acceptance import accept


class BundleAcceptanceTests(unittest.TestCase):
    setUp = fixtures.AdapterEvaluationTests.setUp

    def prepare(self, remote):
        remote.side_effect = lambda endpoint,request: {'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[event(0,1)]} for _ in request['cases']]}}
        self.bundle = build(self.store,self.candidate,'vision_rsi.adapter_fixture','predict',self.contract,self.root/'bundles',media_input=True)
        sample = json.loads(json.dumps(self.data['samples'][0]))
        for name,value in sample['inputs'].items():
            for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                item['uri']=name+str(index)+'.bin'; (self.root/item['uri']).write_bytes(item['uri'].encode())
        development = run(self.bundle['path'],[sample],{},self.root/'development',media_directory=self.root)
        heldout = json.loads(json.dumps(sample)); heldout['sample_id']='holdout'
        for name,value in heldout['inputs'].items():
            for index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                item['uri']='heldout-'+name+str(index)+'.bin'; (self.root/item['uri']).write_bytes(item['uri'].encode())
        self.data = {'purpose':'independent_acceptance','samples':[heldout],
                     'ground_truth':{'labels':['action'],'samples':[{'sample_id':'holdout','events':[event(0,1)]}]}}
        self.dataset.write_text(json.dumps(self.data))
        return development, sample, heldout

    @patch('vision_rsi.remote.check_candidate')
    def test_sealed_metric_reuse_and_changed_input_refusal(self, remote):
        development,_,heldout = self.prepare(remote)
        args = (self.bundle['path'],self.dataset,[development['execution_path']],{},self.root/'acceptance')
        result = accept(*args)
        self.assertEqual(result['status'],'holdout_metric_met')
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['complete_development_history_verified'])
        self.assertEqual(accept(*args),result); self.assertEqual(remote.call_count,2)
        request = remote.call_args.args[1]
        self.assertNotIn('ground_truth',json.dumps(request))
        self.assertNotIn('acceptance',json.dumps(request['cases']))
        first = heldout['inputs']['views']['items'][0]['uri']
        (self.root/first).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'sealed'): accept(*args)
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_renamed_overlap_refused_before_remote(self, remote):
        development,sample,_ = self.prepare(remote)
        self.data['samples'] = [dict(sample,sample_id='holdout')]
        self.dataset.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError,'overlap'):
            accept(self.bundle['path'],self.dataset,[development['execution_path']],{},self.root/'acceptance')
        self.assertEqual(remote.call_count,1)
        self.assertFalse((self.root/'acceptance'/'seal.json').exists())

    @patch('vision_rsi.remote.check_candidate')
    def test_input_changed_between_preflight_and_execution_refused(self, remote):
        development,_,heldout = self.prepare(remote)
        original_run = run
        def changed(*args,**kwargs):
            (self.root/heldout['inputs']['views']['items'][0]['uri']).write_bytes(b'changed after seal')
            return original_run(*args,**kwargs)
        with patch('vision_rsi.bundle_acceptance.run',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'input content changed'):
                accept(self.bundle['path'],self.dataset,[development['execution_path']],{},self.root/'acceptance')
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_execution_never_resent(self, remote):
        development,_,_ = self.prepare(remote)
        remote.side_effect=RuntimeError('connection lost')
        args=(self.bundle['path'],self.dataset,[development['execution_path']],{},self.root/'acceptance')
        with self.assertRaisesRegex(RuntimeError,'connection lost'): accept(*args)
        with self.assertRaisesRegex(RuntimeError,'Uncertain'): accept(*args)
        self.assertEqual(remote.call_count,2)

    @patch('vision_rsi.remote.check_candidate')
    def test_failed_metric_is_retained_and_cached_execution_tampering_refused(self, remote):
        development,_,_ = self.prepare(remote)
        remote.side_effect=lambda endpoint,request:{'status':'executed_unverified','source_hashes':request['source_hashes'],
            'limits':{'gpu':False,'network':False},'observation':{'results':[{'events':[]}]}}
        args=(self.bundle['path'],self.dataset,[development['execution_path']],{},self.root/'acceptance')
        result=accept(*args)
        self.assertEqual(result['status'],'holdout_metric_not_met')
        self.assertEqual(accept(*args),result);self.assertEqual(remote.call_count,2)
        path=Path(result['execution_path']);record=json.loads(path.read_text());record['outputs']=[{'events':[event(0,1)]}]
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'integrity'):accept(*args)
        self.assertEqual(remote.call_count,2)
