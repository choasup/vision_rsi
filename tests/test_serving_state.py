import copy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
import vision_rsi


class ServingStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The production worker is Linux-only; exercise pure state validation
        # on Windows without replacing its real Linux lock in deployed tests.
        with patch.dict(sys.modules,fcntl=SimpleNamespace()):
            scope=runpy.run_path(str(Path(vision_rsi.__file__).with_name('serving.py')),run_name='serving_state_fixture')
        cls.validate=staticmethod(scope['validate_state'])

    def test_valid_states_preserve_observed_cost_including_overshoot(self):
        for status in ('pending','processing','failed','evaluated'):
            state={'status':status,'spent_wall_seconds':120.25,'items':{'1':{'file_sha256':'a'*64,'image_sha256':'b'*64}},'total_images':3}
            original=copy.deepcopy(state);self.validate(state);self.assertEqual(state,original)

    def test_invalid_cost_cache_status_and_coverage_refuse_without_mutation(self):
        base={'status':'pending','spent_wall_seconds':1,'items':{}}
        cases=[]
        for value in (-1,True,None,'0',float('nan'),float('inf')):
            cases.append(dict(base,spent_wall_seconds=value))
        for value in ([],None,{'01':{}},{'1':{}},{'١':{}},{'1':{'file_sha256':'a'*64,'image_sha256':'bad'}}):
            cases.append(dict(base,items=value))
        for value in ('unknown',None):cases.append(dict(base,status=value))
        for value in (0,-1,True,None,1.5):cases.append(dict(base,total_images=value))
        cases.append(dict(base,total_images=1,items={str(i):{'file_sha256':'a'*64,'image_sha256':'b'*64} for i in (1,2)}))
        for state in cases:
            before=json.dumps(state,sort_keys=True)
            with self.subTest(state=state),self.assertRaises(ValueError):self.validate(state)
            self.assertEqual(json.dumps(state,sort_keys=True),before)
