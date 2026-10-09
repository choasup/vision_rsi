import tempfile
import unittest
from vision_rsi.app import TaskService


class AppTests(unittest.TestCase):
    def test_submit_dedup_and_pause_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            service=TaskService(folder,{},'.')
            task=service.create('goal','request1')
            self.assertEqual(task,service.create('goal','request1'))
            self.assertEqual(len(service.tasks()),1)
            self.assertEqual(service.ledger(task).events()[0]['payload']['summary'],'goal')
            with self.assertRaises(ValueError):service.create('different','request1')
            service.control(task,'pause')
            self.assertEqual(service.tasks()[0]['status'],'paused')
            service.control(task,'resume')
            self.assertEqual(service.tasks()[0]['status'],'queued')

    def test_restart_does_not_rerun_uncertain_task(self):
        with tempfile.TemporaryDirectory() as folder:
            service=TaskService(folder,{},'.')
            task=service.create('goal','request1')
            service.set_status(task,'running')
            restarted=TaskService(folder,{},'.')
            self.assertEqual(restarted.tasks()[0]['status'],'interrupted')
            self.assertEqual(len(restarted.ledger(task).events()),1)
            with self.assertRaises(ValueError):restarted.ledger('../escape')
