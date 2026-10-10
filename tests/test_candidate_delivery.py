import json
import unittest
from unittest.mock import patch

import test_research_history as fixtures
from test_candidate_runtime import identity
from vision_rsi.candidate_delivery import promote
from vision_rsi.candidate_serving import check
from vision_rsi.research_history import accept
from vision_rsi.batch import batch


class CandidateDeliveryTests(unittest.TestCase):
    setUp=fixtures.ResearchHistoryTests.setUp
    history=fixtures.ResearchHistoryTests.history

    def ready(self,remote):
        runtime=dict(identity(),protocol='vision-rsi/frozen-cpu-runtime/v2',userspace_sha256='c'*64,userspace_files=1,userspace_bytes=12)
        self.history(remote,runtime=runtime)
        accept(self.registry,self.session,self.delivery['version'],self.holdout,{},self.research_root)
        check(self.registry,self.session,self.delivery['version'],self.holdout,{},30)
        result=promote(self.registry,self.session,self.delivery['version'],self.research_root,{})
        self.sample=json.loads(self.holdout.read_text())['samples'][0]
        self.sample['sample_id']='new-input'
        self.input=self.folder/'input.json';self.input.write_text(json.dumps(self.sample))
        return result

    @patch('vision_rsi.remote.check_candidate')
    def test_promoted_task_single_and_batch_recovery(self,remote):
        delivery=self.ready(remote);self.assertEqual(remote.call_count,4)
        self.assertEqual(self.registry.resolve_version(self.session['task_id']),delivery['version'])
        result=self.registry.infer(self.session['task_id'],self.input)
        self.assertEqual(result['version'],delivery['version'])
        self.assertEqual(result['sample_id'],'new-input')
        self.assertFalse(result['acceptance']['production_accepted'])
        self.assertFalse(result['acceptance']['complete_development_history_verified'])
        self.assertEqual(self.registry.infer(self.session['task_id'],self.input),result)
        self.assertEqual(remote.call_count,5)
        rows=[{'sample_id':'batch-alias','input':str(self.input)}]
        output=self.root/'batch'
        summary=batch(self.registry,self.session['task_id'],rows,output)
        self.assertEqual(summary['succeeded'],1)
        self.assertEqual(batch(self.registry,self.session['task_id'],rows,output,resume=True),summary)
        self.assertEqual(remote.call_count,6)
        self.assertEqual(promote(self.registry,self.session,self.delivery['version'],self.research_root,{}),delivery)
        import subprocess,sys
        from pathlib import Path
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'test','--task-id',self.session['task_id'],'--input',str(self.input),'--registry',str(self.registry.root)]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        self.assertEqual(remote.call_count,6)
        (self.root/'config.json').write_text(json.dumps({'remote':{}}))
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'training','promote-candidate','--session-id',self.session['session_id'],
                 '--version',self.delivery['version'],'--sessions',str(self.root/'sessions'),
                 '--research-root',str(self.research_root),'--registry',str(self.registry.root),
                 '--config',str(self.root/'config.json')]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),delivery)
        self.assertEqual(remote.call_count,6)

    @patch('vision_rsi.remote.check_candidate')
    def test_canonical_joint_sample_batch_preserves_fields_and_grouping(self,remote):
        from vision_rsi.batch import input_rows
        self.ready(remote)
        manifest=self.folder/'samples.jsonl';manifest.write_text(json.dumps(self.sample)+'\n')
        summary=batch(self.registry,self.session['task_id'],input_rows(manifest=manifest),self.root/'canonical')
        self.assertEqual(summary['succeeded'],1)
        self.assertEqual(remote.call_count,5)
        request=remote.call_args.args[1]
        self.assertEqual(len(request['cases']),1)
        self.assertEqual(set(request['cases'][0]['sample']['inputs']),set(self.sample['inputs']))

    @patch('vision_rsi.remote.check_candidate')
    def test_uncertain_formal_inference_never_redispatched(self,remote):
        self.ready(remote);remote.side_effect=RuntimeError('lost connection')
        with self.assertRaisesRegex(RuntimeError,'lost connection'):
            self.registry.infer(self.session['task_id'],self.input)
        with self.assertRaises(RuntimeError):
            self.registry.infer(self.session['task_id'],self.input)
        self.assertEqual(remote.call_count,5)

    @patch('vision_rsi.remote.check_candidate')
    def test_changed_sealed_history_refused_before_inference(self,remote):
        self.ready(remote)
        self.ledger.append('later','evidence',{'summary':'changed history'})
        with self.assertRaisesRegex(ValueError,'unchanged sealed'):
            self.registry.infer(self.session['task_id'],self.input)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_media_drift_refused_before_dispatch(self,remote):
        delivery=self.ready(remote)
        fingerprint=self.registry.input_fingerprint(self.session['task_id'],self.input)
        value=next(iter(self.sample['inputs'].values()))
        item=value['items'][0] if value['type']=='image_list' else value
        (self.folder/item['uri']).write_bytes(b'changed actual media')
        with self.assertRaisesRegex(ValueError,'changed after batch snapshot'):
            self.registry.infer(self.session['task_id'],self.input,delivery['version'],fingerprint)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_media_repack_drift_refused_before_dispatch(self,remote):
        import copy
        from vision_rsi.input_provenance import manifest
        self.ready(remote)
        def changed(contract,cases):
            rows=copy.deepcopy(manifest(contract,cases))
            rows[0]['input_content_sha256']='0'*64
            return rows
        with patch('vision_rsi.candidate_inference.manifest',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed before candidate dispatch'):
                self.registry.infer(self.session['task_id'],self.input)
        self.assertEqual(remote.call_count,4)

    @patch('vision_rsi.remote.check_candidate')
    def test_without_sealed_acceptance_never_promotes(self,remote):
        self.history(remote)
        with self.assertRaises((ValueError,OSError)):
            promote(self.registry,self.session,self.delivery['version'],self.research_root,{})
        with self.assertRaisesRegex(ValueError,'No validated'):
            self.registry.resolve_version(self.session['task_id'])
        self.assertEqual(remote.call_count,1)
