import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.candidate_runtime import _ldd_paths, _file_identity, _elf_executable, freeze_userspace, verify_userspace, validate_runtime_identity
from vision_rsi.runner import digest
from test_candidate_runtime import identity


class RuntimeUserspaceTests(unittest.TestCase):
    def test_relocatable_elf_is_data_not_a_dynamic_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'elf'
            for kind,expected in ((1,False),(2,True),(3,True)):
                header=bytearray(20);header[:4]=b'\x7fELF';header[5]=1;header[16:18]=kind.to_bytes(2,'little')
                path.write_bytes(header);self.assertEqual(_elf_executable(path),expected)

    def test_native_dependency_parser_preserves_alias_names(self):
        value='linux-vdso.so.1 (0x1)\nlibz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x2)\n /lib64/ld-linux-x86-64.so.2 (0x3)'
        self.assertEqual([p.as_posix() for p in _ldd_paths(value)],['/lib/x86_64-linux-gnu/libz.so.1','/lib64/ld-linux-x86-64.so.2'])
        with self.assertRaisesRegex(ValueError,'Missing native'):_ldd_paths('libbad.so => not found')
        with self.assertRaisesRegex(ValueError,'Unrecognized'):_ldd_paths('unexpected diagnostic')

    def test_snapshot_reuse_and_content_tamper_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'source';source.write_bytes(b'fixture binary')
            name='/usr/bin/python3.12';row=_file_identity(source)
            manifest={'format':'vision-rsi/cpu-userspace/v1','entries':{name:row},'files':1,'bytes':row['bytes']}
            with patch('vision_rsi.candidate_runtime.userspace_spec',return_value=(manifest,{name:source})):
                root,actual,checksum=freeze_userspace(folder/'workspace')
                self.assertEqual(checksum,digest(manifest))
                self.assertEqual(freeze_userspace(folder/'workspace'),(root,actual,checksum))
                target=root/name.lstrip('/');target.chmod(0o755);target.write_bytes(b'changed binary')
                with self.assertRaisesRegex(ValueError,'content differs'):freeze_userspace(folder/'workspace')

    def test_extra_namespace_file_and_v2_bounds_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'usr/bin/python3.12';path.parent.mkdir(parents=True);path.write_bytes(b'fixture')
            manifest={'entries':{'/usr/bin/python3.12':_file_identity(path)}}
            verify_userspace(root,manifest)
            (path.parent/'extra').write_bytes(b'not in manifest')
            with self.assertRaisesRegex(ValueError,'content differs'):verify_userspace(root,manifest)
        value=dict(identity(),protocol='vision-rsi/frozen-cpu-runtime/v2',userspace_sha256='c'*64,userspace_files=1,userspace_bytes=12)
        self.assertTrue(validate_runtime_identity(value,digest(value)))
        value['userspace_files']=4097
        with self.assertRaisesRegex(ValueError,'exceeds bounds'):validate_runtime_identity(value,digest(value))
