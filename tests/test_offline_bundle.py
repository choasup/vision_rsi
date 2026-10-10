import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('bundle_installer',Path(__file__).resolve().parents[1]/'tools/install_bundle.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class OfflineBundleTests(unittest.TestCase):
    def test_tampered_or_escaping_payload_rejected_before_environment_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'agent.whl').write_bytes(b'developer verification fixture')
            (root/'requirements.lock').write_bytes(b'fixture')
            manifest={'format':'vision-rsi-offline-bundle-v1','agent_wheel':'agent.whl',
                      'files':{name:installer.checksum(root/name) for name in ('agent.whl','requirements.lock')}}
            path=root/'bundle.json';path.write_text(json.dumps(manifest),encoding='utf-8')
            self.assertEqual(installer.verify(root)['agent_wheel'],'agent.whl')
            (root/'agent.whl').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):installer.verify(root)
            self.assertFalse((root/'venv').exists())
            manifest['files']={'../outside': 'a'*64}
            path.write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'plain filenames'):installer.verify(root)
            self.assertFalse((root/'venv').exists())
