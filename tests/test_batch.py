import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.batch import batch,input_rows
from vision_rsi.capability import Capabilities

class BatchTests(unittest.TestCase):
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
