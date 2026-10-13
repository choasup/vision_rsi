import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.cpu_experiment import predict,run,checksum


class CPUExperimentTests(unittest.TestCase):
    def test_prediction_export_is_reloadable_and_refuses_overwriting_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model={'classes':['0','1'],'coefficients':[[0]*64,[0]*64],'intercepts':[0,2]}
            (root/'model.json').write_text(json.dumps(model))
            (root/'input.json').write_text(json.dumps([{'sample_id':'sample','pixels':[0]*64}]))
            result=predict(str(root/'model.json'),str(root/'input.json'),str(root/'prediction.json'))
            self.assertEqual(result[0]['label'],'1')
            self.assertGreater(result[0]['confidence'],.8)
            with self.assertRaises(ValueError):predict(root/'model.json',root/'input.json',root/'model.json')
            self.assertEqual(json.loads((root/'model.json').read_text()),model)
            model['coefficients'][0]=[0]
            (root/'model.json').write_text(json.dumps(model))
            with self.assertRaisesRegex(ValueError,'dimensions'):
                predict(root/'model.json',root/'input.json',root/'invalid-prediction.json')
            self.assertFalse((root/'invalid-prediction.json').exists())

    @unittest.skipUnless(importlib.util.find_spec('sklearn'),'Install the cpu extra for real training test')
    def test_real_training_split_export_and_heldout_measurement(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            root=Path(directory)/'experiment'
            result=run(root)
            self.assertTrue(result['training_performed'])
            self.assertGreater(result['test_accuracy'],.9)
            self.assertEqual(result['test_total'],360)
            self.assertFalse(result['user_acceptance_verified'])
            splits=json.loads((root/'splits.json').read_text())
            groups=[set(splits[key]) for key in ('train','development','test')]
            self.assertEqual(sum(map(len,groups)),1797)
            self.assertEqual(len(set.union(*groups)),1797)
            self.assertEqual(len(set(splits['image_sha256'])),1797)
            self.assertTrue(all('label' not in row for row in json.loads((root/'test-inputs.json').read_text())))
            for name,value in json.loads((root/'artifacts.json').read_text()).items():
                self.assertEqual(checksum(root/name),value)
            self.assertTrue(result['exported_predictions_match_sklearn'])
            with self.assertRaises(FileExistsError):run(root)


if __name__=='__main__':unittest.main()
