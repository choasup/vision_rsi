import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch
from vision_rsi.coco_infer import cpu_runtime_identity,load_runtime


class CpuRuntimeTests(unittest.TestCase):
    @patch('vision_rsi.coco_infer.cpu_runtime_identity',return_value=({'fixture':True},'b'*64))
    def test_changed_environment_refuses_loading_model(self,identity):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);bundle=root/'releases/bundle';bundle.mkdir(parents=True)
            recipe={'fixture':True};(bundle/'recipe.json').write_text(json.dumps(recipe))
            checkpoint=root/'training/checkpoint.pt';checkpoint.parent.mkdir();checkpoint.write_bytes(b'fixture')
            request={'workspace':str(root),'bundle_directory':str(bundle),'source_hashes':{},'recipe':recipe,
                     'checkpoint':str(checkpoint),'checkpoint_sha256':hashlib.sha256(b'fixture').hexdigest(),
                     'contract':{'inputs':{'image':{'type':'image'}}},'serving_runtime_sha256':'a'*64}
            torch=N(__version__='2.6.0+cu124',set_num_threads=lambda n:None)
            vision=N(__version__='0.21.0+cu124')
            # Production uses Linux paths; permit this fixture's local Windows root.
            with patch('vision_rsi.coco_infer.PurePosixPath',Path),patch.dict(sys.modules,torch=torch,torchvision=vision),patch.object(sys,'path',list(sys.path)):
                with self.assertRaisesRegex(ValueError,'runtime differs'):load_runtime(request)

    @patch('importlib.metadata.version')
    def test_fingerprint_changes_with_cpu_dependency_and_threads(self,version):
        packages={'torch':'2.6.0+cu124','torchvision':'0.21.0+cu124','Pillow':'fixture','numpy':'fixture','pycocotools':'2.0.11'}
        version.side_effect=packages.__getitem__
        torch=N(__version__=packages['torch'],__config__=N(show=lambda:'fixture build'),get_num_threads=lambda:4,
                get_num_interop_threads=lambda:8,are_deterministic_algorithms_enabled=lambda:False,
                get_float32_matmul_precision=lambda:'highest')
        vision=N(__version__=packages['torchvision'])
        first,sha=cpu_runtime_identity(torch,vision)
        self.assertEqual((first,sha),cpu_runtime_identity(torch,vision))
        packages['Pillow']='changed'
        self.assertNotEqual(sha,cpu_runtime_identity(torch,vision)[1])
        packages['Pillow']='fixture';torch.get_num_threads=lambda:2
        self.assertNotEqual(sha,cpu_runtime_identity(torch,vision)[1])
        packages['torch']='2.6.0';packages['torchvision']='0.21.0'
        self.assertEqual(cpu_runtime_identity(torch,vision)[0]['modules']['torch'],'2.6.0+cu124')
        packages['torch']='wrong'
        with self.assertRaisesRegex(ValueError,'module and installed'):cpu_runtime_identity(torch,vision)
