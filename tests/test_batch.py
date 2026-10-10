import json
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from vision_rsi.batch import batch,input_rows,LOCK_MARKER
from vision_rsi.campaign import lease
from vision_rsi.capability import Capabilities

class FixtureRegistry:
    def __init__(self):self.calls=[]
    def resolve_version(self,task,version):return version or 'fixture-v1'
    def infer(self,task,path,version):
        self.calls.append(Path(path).name)
        return {'output':{'fixture_text':Path(path).read_text()},'acceptance':{'fixture':True}}

class BatchTests(unittest.TestCase):
    def test_later_changed_input_or_cached_output_blocks_earlier_retry_before_dispatch(self):
        class FailFirst(FixtureRegistry):
            def infer(self,task,path,version):
                if Path(path).name=='first.txt':
                    self.calls.append('first.txt');raise RuntimeError('Synthetic transient failure')
                return super().infer(task,path,version)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=root/'first.txt';second=root/'second.txt'
            first.write_text('first');second.write_text('second')
            rows=[{'sample_id':'first','input':str(first)},{'sample_id':'second','input':str(second)}]
            folder=root/'output';registry=FailFirst()
            result=batch(registry,'fixture',rows,folder)
            self.assertEqual(result['failed'],1)
            before=(folder/'batch-state.json').read_bytes()
            registry.calls.clear();second.write_text('changed')
            with self.assertRaisesRegex(ValueError,'content changed'):
                batch(registry,'fixture',rows,folder,resume=True)
            self.assertEqual(registry.calls,[])
            self.assertEqual((folder/'batch-state.json').read_bytes(),before)
            second.write_text('second')
            state=json.loads(before)
            (folder/state['items']['second']['output_file']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'output missing or changed'):
                batch(registry,'fixture',rows,folder,resume=True)
            self.assertEqual(registry.calls,[])
            self.assertEqual((folder/'batch-state.json').read_bytes(),before)

    def test_actual_process_death_releases_lock_and_resume_skips_saved_success(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);first=root/'first.txt';second=root/'second.txt'
            first.write_text('first fixture');second.write_text('second fixture')
            rows=[{'sample_id':'first','input':str(first)},{'sample_id':'second','input':str(second)}]
            rows_file=root/'rows.json';rows_file.write_text(json.dumps(rows))
            ready=root/'ready';output=root/'results'
            program='''import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from test_batch import FixtureRegistry
from vision_rsi.batch import batch
class Pause(FixtureRegistry):
 def infer(self,task,path,version):
  if Path(path).name=='second.txt':
   Path(sys.argv[4]).write_text('second inference entered')
   time.sleep(60)
  return super().infer(task,path,version)
batch(Pause(),'fixture',json.loads(Path(sys.argv[2]).read_text()),sys.argv[3])
'''
            child=subprocess.Popen([sys.executable,'-c',program,str(Path(__file__).parent.resolve()),str(rows_file),str(output),str(ready)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+10
                while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(ready.exists(),'Child failed before second inference')
                child.kill();child.communicate(timeout=5)
                state=json.loads((output/'batch-state.json').read_text())
                self.assertEqual(set(state['items']),{'first'})
                registry=FixtureRegistry()
                result=batch(registry,'fixture',rows,output,resume=True)
                self.assertEqual(result['succeeded'],2)
                self.assertEqual(registry.calls,['second.txt'])
                self.assertEqual((output/'batch.lock').read_bytes(),LOCK_MARKER)
                with self.assertRaisesRegex(ValueError,'capability version changed'):
                    batch(registry,'fixture',rows,output,version='fixture-v2',resume=True)
            finally:
                if child.poll() is None:child.kill()
                child.communicate(timeout=5)

    def test_active_os_lease_and_ambiguous_legacy_lock_are_not_removed(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);output=root/'results';output.mkdir();lock=output/'batch.lock'
            registry=FixtureRegistry();rows=[{'sample_id':'one','input':str(root/'unused')}]
            lock.write_bytes(b'')
            with self.assertRaisesRegex(RuntimeError,'Legacy or invalid'):
                batch(registry,'fixture',rows,output)
            self.assertEqual(lock.read_bytes(),b'');self.assertEqual(registry.calls,[])
            lock.write_bytes(LOCK_MARKER)
            with lease(lock):
                with self.assertRaisesRegex(RuntimeError,'Batch inference is already active'):
                    batch(registry,'fixture',rows,output)
            self.assertEqual(lock.read_bytes(),LOCK_MARKER)
            self.assertFalse((output/'batch-state.json').exists())

    @patch('vision_rsi.capability.revision',return_value='fixture')
    def test_mixed_failure_resume_and_changed_input(self,_):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);registry=Capabilities(root/'registry')
            try:
                trained=registry.train('examples/toy-task.json')
                valid=root/'good.json';valid.write_text(Path('examples/toy-input.json').read_text())
                invalid=root/'bad.json';invalid.write_text('{"image":[]}')
                manifest=root/'samples.jsonl';manifest.write_text(json.dumps({'sample_id':'good','input':'good.json'})+'\n'+json.dumps({'sample_id':'bad','input':'bad.json'})+'\n')
                rows=input_rows(manifest=manifest)
                result=batch(registry,'bright-object',rows,root/'results')
                self.assertEqual((result['succeeded'],result['failed']),(1,1))
                with patch.object(registry,'infer',wraps=registry.infer) as infer:
                    batch(registry,'bright-object',rows,root/'results',resume=True)
                    self.assertEqual(infer.call_count,1)
                valid.write_text('{"image":[[255]]}')
                with self.assertRaisesRegex(ValueError,'content changed'):
                    batch(registry,'bright-object',rows,root/'results',resume=True)
            finally:registry.close()
    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'batch.jsonl';path.write_text('{"sample_id":"same","input":"x"}\n'*2)
            with self.assertRaisesRegex(ValueError,'Duplicate'):input_rows(manifest=path)
    @patch('vision_rsi.capability.revision',return_value='fixture')
    def test_saved_output_tamper_is_detected(self,_):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);registry=Capabilities(root/'registry')
            try:
                registry.train('examples/toy-task.json')
                rows=[{'sample_id':'one','input':str(Path('examples/toy-input.json').resolve())}]
                batch(registry,'bright-object',rows,root/'results')
                state=json.loads((root/'results'/'batch-state.json').read_text())
                (root/'results'/state['items']['one']['output_file']).write_text('{}')
                with self.assertRaisesRegex(ValueError,'output missing or changed'):
                    batch(registry,'bright-object',rows,root/'results',resume=True)
            finally:registry.close()
