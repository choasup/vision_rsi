import io
import json
import os
import unittest
from unittest.mock import patch
from vision_rsi.credentials import read_key
from vision_rsi.llm import OpenAICompatibleClient
from vision_rsi.runner import doctor


class CredentialTests(unittest.TestCase):
    @patch('vision_rsi.credentials._windows_user_key',return_value='USER_SECRET')
    def test_process_override_wins_without_registry_lookup(self,user):
        with patch.dict(os.environ,{'FIXTURE_CREDENTIAL':'PROCESS_SECRET'}):
            self.assertEqual(read_key('FIXTURE_CREDENTIAL'),('PROCESS_SECRET','process_environment'))
        user.assert_not_called()

    @patch('vision_rsi.credentials._windows_user_key',return_value='USER_SECRET')
    @patch('vision_rsi.llm.urlopen')
    def test_user_environment_fallback_used_by_client_and_doctor_without_export(self,network,user):
        config={'api_key_env':'FIXTURE_CREDENTIAL','model':'fixture','base_url':'https://example.invalid'}
        with patch.dict(os.environ,{},clear=True):
            report=doctor({'llm':config})
            self.assertTrue(report['api_key_present'])
            self.assertEqual(report['api_key_scope'],'windows_user_environment')
            self.assertNotIn('USER_SECRET',json.dumps(report))
            self.assertNotIn('FIXTURE_CREDENTIAL',os.environ)
            network.return_value=io.BytesIO(json.dumps({'choices':[{'message':{'content':'fixture'}}]}).encode())
            OpenAICompatibleClient(config).complete([{'role':'user','content':'fixture'}])
            self.assertEqual(network.call_args.args[0].get_header('Authorization'),'Bearer USER_SECRET')
            self.assertNotIn('FIXTURE_CREDENTIAL',os.environ)

    @patch('vision_rsi.credentials._windows_user_key')
    def test_invalid_names_do_not_read_registry(self,user):
        for name in (None,[], '', 'x'*257,'bad\x00name'):
            self.assertEqual(read_key(name),(None,'missing'))
        user.assert_not_called()
