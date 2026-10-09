import copy
import unittest
from vision_rsi.strategy_protocol import validate_context,validate_decision


class StrategyProtocolTests(unittest.TestCase):
    def setUp(self):
        self.actions=[{'id':'diagnose','estimated_cost':1,'expected_gain':.2,'uncertainty':.1},
                      {'id':'train','estimated_cost':8,'expected_gain':3,'uncertainty':.2}]
    def test_available_affordable_or_stop(self):
        validate_decision([],self.actions,1,{'action_id':'diagnose','rationale':'Affordable diagnostic'})
        validate_decision([],self.actions,0,{'action_id':None,'rationale':'No remaining budget'})
        for selected in ('train','invented'):
            with self.assertRaises(ValueError):validate_decision([],self.actions,1,{'action_id':selected,'rationale':'Invalid'})
        with self.assertRaisesRegex(ValueError,'already attempted'):
            validate_decision([{'id':'diagnose','status':'failed'}],self.actions,10,{'action_id':'diagnose','rationale':'Retry without attempt identity'})
    def test_numeric_and_duplicate_guards(self):
        for key,value in [('estimated_cost',0),('estimated_cost',-1),('estimated_cost',True),('expected_gain',float('nan')),('uncertainty',-1)]:
            actions=copy.deepcopy(self.actions);actions[0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_context([],actions,10)
        with self.assertRaises(ValueError):validate_context([],self.actions*2,10)
        with self.assertRaises(ValueError):validate_context([],self.actions,float('inf'))
