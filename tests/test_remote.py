import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from vision_rsi.remote import probe, ssh_argv


class RemoteTests(unittest.TestCase):
    def test_host_and_port_validation(self):
        for host in ['', '-oProxyCommand=bad', 'host; command', 'host name']:
            with self.assertRaises(ValueError):
                ssh_argv({'ssh_host': host})
        for port in [True, 0, 65536, '22']:
            with self.assertRaises(ValueError):
                ssh_argv({'ssh_host': 'fixture', 'ssh_port': port})
        argv = ssh_argv({'ssh_host': 'root@example.invalid', 'ssh_port': 10820})
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('BatchMode=yes', argv)

    @patch('vision_rsi.remote.subprocess.run')
    def test_probe_protocol(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps({'devices': 8}))
        self.assertEqual(probe({'ssh_host': 'fixture'}), {'devices': 8})
        self.assertIn('import importlib', run.call_args.kwargs['input'])
        self.assertEqual(run.call_args.kwargs['timeout'], 90)
        self.assertEqual(run.call_args.args[0][-1], 'python3 -')

    @patch('vision_rsi.remote.subprocess.run')
    def test_failure_not_success(self, run):
        run.return_value = SimpleNamespace(returncode=255, stderr='authentication failed')
        with self.assertRaisesRegex(RuntimeError, 'SSH probe failed'):
            probe({'ssh_host': 'fixture'})
