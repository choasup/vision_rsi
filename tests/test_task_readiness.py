import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vision_rsi.contracts import Sessions
from vision_rsi.task_readiness import inspect


class TaskReadinessTests(unittest.TestCase):
    def test_missing_stores_are_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'ledger missing'):inspect('missing',{},root/'sessions',root/'runs')
            self.assertEqual(list(root.iterdir()),[])

    @patch('vision_rsi.task_readiness.doctor',return_value={'configuration_ready':True})
    def test_readonly_report_preserves_ledgers_and_missing_budget_is_not_authorized(self,doctor):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Sessions(root/'sessions')
            session=store.create('fixture','Synthetic readiness only')
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
            contract['budget']=None;store.define(session['session_id'],contract)
            path=root/'sessions/sessions.sqlite3';before=path.read_bytes()
            report=inspect(session['session_id'],{},root/'sessions',root/'runs')
            self.assertEqual(report['status'],'blocked');self.assertIsNone(report['authorized_gpu_hours'])
            self.assertFalse(report['release_verified']);self.assertEqual(report['task_quality_status'],'not_checked')
            self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'runs').exists())
            with self.assertRaises(sqlite3.OperationalError):
                with Sessions(root/'sessions',read_only=True).db() as db:db.execute('DELETE FROM sessions')
            self.assertEqual(path.read_bytes(),before)

    @patch('vision_rsi.task_readiness.doctor',return_value={'configuration_ready':True})
    def test_compatible_authorized_fixture_is_only_ready_for_prepare_not_quality(self,doctor):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Sessions(root/'sessions')
            session=store.create('fixture','Synthetic compatibility only')
            contract={'goal':'COCO detection','inputs':{'image':{'type':'image','required':True}},
                      'output_schema':{'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}},
                      'acceptance':{'metric':'box_AP','threshold':60,'direction':'maximize','evaluation_protocol':'COCO bbox AP'},
                      'budget':{'gpu_hours':1},'assumptions':[],'open_questions':[],
                      'example_input':{'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.jpg'}}},'example_output':{'detections':[]}}
            store.define(session['session_id'],contract)
            report=inspect(session['session_id'],{},root/'sessions',root/'runs')
            self.assertEqual(report['status'],'ready_for_prepare');self.assertEqual(report['remaining_gpu_hours_snapshot'],1)
            self.assertFalse(report['training_performed']);self.assertFalse(report['release_verified'])
            self.assertEqual(report['task_quality_status'],'not_checked')
