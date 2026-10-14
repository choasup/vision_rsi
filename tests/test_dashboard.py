import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.dashboard import configuration, access_instructions
from vision_rsi.console import local_host
from launch_agent import task_cli_paths


class DashboardStartupTests(unittest.TestCase):
    def test_initialize_and_preserve_existing_config(self):
        with tempfile.TemporaryDirectory() as d:
            root, path, config = configuration(d)
            config['custom'] = 'preserve'
            path.write_text(json.dumps(config))
            self.assertEqual(configuration(d)[2]['custom'], 'preserve')
            (root/'works').mkdir()
            (root/'works/config.local.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, '两份'):
                configuration(d)
            self.assertEqual(configuration(d, path)[2]['custom'], 'preserve')

    def test_source_launcher_keeps_workspace_and_config_relative_to_caller(self):
        caller = Path('/tmp/my-workspace')
        args = task_cli_paths(['dashboard', '--config', './existing.json'], caller)
        self.assertIn(str(caller/'existing.json'), args)
        self.assertIn(str(caller), args)

    def test_ssh_instructions_use_actual_selected_port(self):
        text = access_instructions(8783, {'SSH_CONNECTION': '10.0.0.1 1234 10.0.0.2 2222'})
        self.assertIn('-L 8783:127.0.0.1:8783', text)
        self.assertIn('-p 2222', text)
        self.assertIn('你电脑', text)
        self.assertNotIn('ssh -N', access_instructions(8780, {}))

    def test_only_loopback_hosts_including_forwarded_ports(self):
        for host in ('localhost:8780', '127.0.0.1:9999', 'localhost'):
            self.assertTrue(local_host(host))
        for host in ('evil.test:8780','localhost.evil:8780','127.0.0.1:99999',None):
            self.assertFalse(local_host(host))
