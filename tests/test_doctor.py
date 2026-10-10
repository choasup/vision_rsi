import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.runner import doctor


class DoctorTests(unittest.TestCase):
    def test_configured_report_does_not_disclose_secrets_or_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Path(folder)/'absent/usage.sqlite3'
            config={'mode':'mock','llm':{'model':'fixture','base_url':'https://example.invalid','api_key_env':'FIXTURE_KEY','usage_ledger':str(ledger)},'remote':{'ssh_host':'fixture','workspace':'/workspace','ssh_port':22}}
            with patch.dict('os.environ',{'FIXTURE_KEY':'PRIVATE_DO_NOT_PRINT'}),patch('shutil.which',return_value='ssh'),patch('subprocess.run') as run,patch('vision_rsi.llm.OpenAICompatibleClient.complete') as complete:
                report=doctor(config);run.assert_not_called();complete.assert_not_called()
            self.assertTrue(report['configuration_ready']);self.assertTrue(report['real_training_implemented'])
            self.assertFalse(ledger.parent.exists());self.assertNotIn('PRIVATE_DO_NOT_PRINT',json.dumps(report))
            for field in ('real_api_tested','remote_connectivity_tested','training_performed','task_budget_checked','task_effect_verified','release_verified'):
                self.assertFalse(report[field])

    def test_missing_or_malformed_config_does_not_become_ready(self):
        for config in ({},{'llm':[],'remote':[]},{'llm':{'api_key_env':[]},'remote':{'ssh_host':'bad host','workspace':'relative'}}, {'remote':{'ssh_host':'fixture','workspace':'/bad\npath'}}):
            report=doctor(config);self.assertFalse(report['configuration_ready'])
        with self.assertRaises(ValueError):doctor([])

    def test_https_and_immutable_ledger_limit_validation_are_used_without_creation(self):
        with patch.dict('os.environ',{'FIXTURE_KEY':'secret'}):
            base={'api_key_env':'FIXTURE_KEY','base_url':'https://example.invalid','model':'fixture'}
            for update in ({'base_url':'http://example.invalid'},{'usage_call_limit':True},{'usage_call_limit':2},{'usage_ledger':'relative.sqlite3'}):
                report=doctor({'llm':dict(base,**update)})
                self.assertFalse(report['llm_configuration_valid'])
