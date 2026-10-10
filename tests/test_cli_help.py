import subprocess
import sys
import unittest


class CLIHelpTests(unittest.TestCase):
    def invoke(self,*args):
        result=subprocess.run([sys.executable,'-X','utf8','-m','vision_rsi',*args],
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout

    def test_root_help_and_no_arguments_present_actual_workflow(self):
        for args in ((),('--help',),('-h',)):
            output=self.invoke(*args)
            self.assertIn('training start --task-id',output)
            self.assertIn('training readiness',output)
            self.assertIn('test --task-id TASK --manifest',output)
            self.assertIn('explicit task budget',output)
            self.assertIn('synthetic fixtures',output)
            self.assertIn('video training are incomplete',output)

    def test_training_without_action_shows_task_commands(self):
        output=self.invoke('training')
        self.assertIn('readiness',output)
        self.assertIn('--session-id',output)
        self.assertIn('start',output)

    def test_candidate_infer_dispatches_to_training_parser(self):
        output=self.invoke('training','candidate-infer','--help')
        self.assertIn('--request-id',output)
        self.assertIn('--sample',output)
        self.assertIn('--manifest',output)
