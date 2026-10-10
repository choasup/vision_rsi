import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.runner import revision


class RevisionTests(unittest.TestCase):
    def test_installed_identity_uses_package_bytes_not_caller_git(self):
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder)/'site-packages/vision_rsi';package.mkdir(parents=True)
            source=package/'runner.py';source.write_text('source = 1')
            with patch('vision_rsi.runner.__file__',str(source)),patch('vision_rsi.runner.subprocess.check_output') as git:
                first=revision()
                self.assertTrue(first.startswith('source-sha256:'))
                self.assertEqual(first,revision())
                (package/'__pycache__').mkdir();(package/'__pycache__/cache.pyc').write_bytes(b'cache')
                self.assertEqual(first,revision())
                source.write_text('source = 2')
                self.assertNotEqual(first,revision())
                git.assert_not_called()

    def test_checkout_identity_anchors_git_to_package_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.git').write_text('gitdir: worktree')
            package=root/'vision_rsi';package.mkdir();source=package/'runner.py';source.write_text('')
            with patch('vision_rsi.runner.__file__',str(source)),patch('vision_rsi.runner.subprocess.check_output',return_value='a'*40+'\n') as git:
                self.assertEqual(revision(),'a'*40)
                self.assertEqual(git.call_args.args[0],['git','-C',str(root),'rev-parse','HEAD'])
