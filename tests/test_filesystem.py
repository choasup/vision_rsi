import os
from pathlib import Path
import tempfile
import unittest
from vision_rsi.filesystem import native_path
from vision_rsi.runner import atomic_json
import json


class NativePathTests(unittest.TestCase):
    def test_short_paths_keep_their_existing_form(self):
        self.assertEqual(native_path('runs/fixture.json'),Path('runs/fixture.json'))

    def test_real_deep_directory_atomic_write_and_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);created=[]
            for i in range(8):
                directory=directory/('segment-'+str(i)+'-'+'x'*25);created.append(directory)
            directory=native_path(directory);directory.mkdir(parents=True)
            target=native_path(directory/'state.json');value={'fixture':True,'path_test':'long'}
            try:
                atomic_json(target,value)
                self.assertEqual(json.loads(target.read_text(encoding='utf-8')),value)
                self.assertEqual(native_path(target),target)
                self.assertGreater(len(str(target)),260)
                if os.name=='nt':self.assertTrue(str(target).startswith('\\\\?\\'))
            finally:
                target.unlink(missing_ok=True)
                for owned in reversed(created):native_path(owned).rmdir()

    @unittest.skipUnless(os.name=='nt','Windows namespace syntax')
    def test_unc_namespace_conversion_is_lexical_and_does_not_open_share(self):
        value='\\\\server\\share\\'+('segment\\'*40)+'state.json'
        converted=str(native_path(value))
        self.assertTrue(converted.startswith('\\\\?\\UNC\\server\\share\\'))
        self.assertEqual(native_path(converted),Path(converted))
