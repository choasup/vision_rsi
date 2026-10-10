import unittest
from vision_rsi.paired_study import resource_comparison


class StudyResourceTests(unittest.TestCase):
    def arm(self):
        return {'settled_gpu_hours':1.5,'gpu_accounting_settled':True,
                'observed_action_wall_seconds':100,'action_timing_complete':True,
                'known_llm_tokens':200,'llm_usage_complete':True,
                'llm_cost_scope':'Experiment proposals only'}

    def test_observed_deltas_are_not_efficiency_or_budget_proof(self):
        baseline=self.arm();candidate=dict(baseline,settled_gpu_hours=1.,known_llm_tokens=300)
        result=resource_comparison(baseline,candidate)
        self.assertTrue(result['observed_costs_complete'])
        self.assertEqual(result['metrics']['settled_gpu_hours']['candidate_minus_baseline'],-.5)
        self.assertEqual(result['metrics']['known_llm_tokens']['candidate_minus_baseline'],100)
        self.assertFalse(result['equal_resource_budgets_verified'])
        self.assertFalse(result['rsi_efficiency_verified'])

    def test_unknown_or_invalid_costs_stay_unknown(self):
        for metric,flag in [('settled_gpu_hours','gpu_accounting_settled'),
                            ('observed_action_wall_seconds','action_timing_complete'),
                            ('known_llm_tokens','llm_usage_complete')]:
            for value in (None,True,-1,float('nan'),float('inf')):
                candidate=dict(self.arm(),**{metric:value})
                result=resource_comparison(self.arm(),candidate)
                self.assertFalse(result['observed_costs_complete'])
                self.assertIsNone(result['metrics'][metric]['candidate'])
                self.assertIsNone(result['metrics'][metric]['candidate_minus_baseline'])
            candidate=dict(self.arm(),**{flag:False})
            self.assertIsNone(resource_comparison(self.arm(),candidate)['metrics'][metric]['candidate'])
        result=resource_comparison(self.arm(),dict(self.arm(),known_llm_tokens=1.5))
        self.assertFalse(result['observed_costs_complete'])

    def test_mismatched_scope_and_missing_fields_are_incomplete(self):
        result=resource_comparison(self.arm(),dict(self.arm(),llm_cost_scope='Whole project'))
        self.assertFalse(result['observed_costs_complete'])
        result=resource_comparison({}, {})
        self.assertFalse(result['observed_costs_complete'])
        self.assertIsNone(result['metrics']['known_llm_tokens']['baseline'])
