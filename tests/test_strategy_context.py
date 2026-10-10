import copy
import unittest
from vision_rsi.strategy_context import history_context
from vision_rsi.strategy_protocol import validate_context,validate_decision


class StrategyContextTests(unittest.TestCase):
    def test_observations_expose_metrics_method_and_cost_without_paths_or_credentials(self):
        rows=[{'action':{'id':'prepare-0','kind':'prepare'},'status':'completed','result':{'status':'ready_to_submit','recipe':{'learning_rate':.001,'seed':42,'weights':'/private/weights','fixture':True},'api_key':'NEVER_INCLUDE'}},
              {'action':{'id':'analyze-1','kind':'analyze'},'status':'completed','result':{'actual_gpu_hours':.1,'metric_gap':18,'quality_verified':False,'acceptance_review':{'box_AP':42,'threshold':60,'reasons':['Fixture cannot establish quality']}}}]
        original=copy.deepcopy(rows);context=history_context(rows)
        self.assertEqual(context[1]['observation']['measurement']['value'],42)
        self.assertEqual(context[1]['observation']['metric_gap'],18)
        self.assertEqual(context[0]['observation']['method']['learning_rate'],.001)
        self.assertNotIn('private',str(context));self.assertNotIn('NEVER_INCLUDE',str(context));self.assertEqual(rows,original)
        legacy=history_context(rows,1);self.assertNotIn('observation',legacy[1])

    def test_research_brief_only_controls_research_hypothesis(self):
        action={'id':'next','kind':'propose_experiment','estimated_cost':1,'expected_gain':2,'uncertainty':.1}
        decision={'action_id':'next','rationale':'Use measured failure','research_brief':'Test whether lower LR helps; instability is unproven.'}
        self.assertEqual(validate_decision([], [action],1,decision),decision)
        for kind in ('submit','collect','analyze'):
            with self.assertRaises(ValueError):validate_decision([],[dict(action,kind=kind)],1,decision)
        with self.assertRaises(ValueError):validate_decision([],[action],1,dict(decision,action_id=None))
        with self.assertRaises(ValueError):validate_decision([],[action],1,dict(decision,research_brief='x'*6001))

    def test_nonfinite_and_excessive_observations_rejected(self):
        for value in (float('nan'),'x'*(512*1024)):
            with self.assertRaises(ValueError):validate_context([{'id':'old','observation':value}],[],1)
