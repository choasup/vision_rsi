import copy
import unittest
from vision_rsi.strategy_context import history_context
from vision_rsi.strategy_protocol import validate_context,validate_decision


class StrategyContextTests(unittest.TestCase):
    def test_observations_expose_metrics_method_and_cost_without_paths_or_credentials(self):
        rows=[{'action':{'id':'prepare-0','kind':'prepare'},'status':'completed','result':{'status':'ready_to_submit','recipe':{'learning_rate':.001,'seed':42,'weights':'/private/weights','fixture':True},'api_key':'NEVER_INCLUDE'}},
              {'action':{'id':'analyze-1','kind':'analyze'},'status':'completed','result':{'actual_gpu_hours':.1,'metric_gap':18,'quality_verified':False,'acceptance_review':{'box_AP':42,'threshold':60,'reasons':['Fixture cannot establish quality'],'error_summary':{'totals':{'false_negatives':2}}}}}]
        original=copy.deepcopy(rows);context=history_context(rows)
        self.assertEqual(context[1]['observation']['measurement']['value'],42)
        self.assertEqual(context[1]['observation']['metric_gap'],18)
        self.assertEqual(context[1]['observation']['error_summary']['totals']['false_negatives'],2)
        self.assertEqual(context[0]['observation']['method']['learning_rate'],.001)
        self.assertNotIn('private',str(context));self.assertNotIn('NEVER_INCLUDE',str(context));self.assertEqual(rows,original)
        legacy=history_context(rows,1);self.assertNotIn('observation',legacy[1])

    def test_run_snapshots_can_be_deduplicated_and_legacy_context_is_unchanged(self):
        rows=[{'action':{'id':'observe-0','kind':'observe'},'status':'completed',
               'result':{'run_id':'train-one','status':'running','actual_gpu_hours':None,'reserved_gpu_hours':.5}},
              {'action':{'id':'collect-1','kind':'collect'},'status':'completed',
               'result':{'run_id':'train-one','status':'completed','actual_gpu_hours':.2,'reserved_gpu_hours':.5}},
              {'action':{'id':'analyze-2','kind':'analyze'},'status':'completed',
               'result':{'run_id':'train-one','actual_gpu_hours':.2,'authorized_gpu_hours':2,'remaining_gpu_hours':1.3}}]
        original=copy.deepcopy(rows);context=history_context(rows,3)
        self.assertEqual({row['observation']['run_id'] for row in context},{'train-one'})
        self.assertEqual(context[0]['observation']['held_gpu_hours'],.5)
        self.assertEqual(context[1]['observation']['held_gpu_hours'],0)
        self.assertEqual(context[2]['observation']['gpu_cost_scope'],'whole_run_snapshot_not_incremental')
        self.assertEqual(context[2]['observation']['gpu_budget_scope'],'whole_session_snapshot')
        self.assertEqual(context[2]['observation']['remaining_gpu_hours'],1.3)
        for row in history_context(rows,2):
            self.assertNotIn('run_id',row['observation']);self.assertNotIn('gpu_cost_scope',row['observation'])
        self.assertEqual(rows,original)

    def test_long_history_has_deterministic_bounded_view_and_keeps_research(self):
        import json
        rows=[{'action':{'id':'observe-'+str(i),'kind':'observe'},'status':'completed',
               'result':{'run_id':'train-one','status':'running','actual_gpu_hours':None,'reserved_gpu_hours':.5}}
              for i in range(2500)]
        rows[20]={'action':{'id':'analyze-20','kind':'analyze'},'status':'completed',
                  'result':{'run_id':'train-old','actual_gpu_hours':.2,'metric_gap':20,
                            'acceptance_review':{'box_AP':40,'threshold':60,'error_summary':{'large':'x'*20000}}}}
        rows[30]={'action':{'id':'propose-30','kind':'propose_experiment'},'status':'completed',
                  'result':{'experiment':{'proposal':{'hypothesis':'Measured failure needs a separately tested method'}}}}
        original=copy.deepcopy(rows)
        legacy=history_context(rows,3)
        with self.assertRaises(ValueError):validate_context(legacy,[],1)
        view=history_context(rows,4)
        validate_context(view,[],1)
        self.assertLessEqual(len(json.dumps(view,sort_keys=True).encode()),192*1024)
        self.assertEqual(view,history_context(rows,4));self.assertEqual(rows,original)
        summary=view[0]['observation']
        self.assertEqual(summary['total_rows'],2500)
        self.assertEqual(summary['omitted_research_rows'],0)
        self.assertEqual(summary['retained_rows']+summary['omitted_rows'],2500)
        retained={row['id']:row for row in view}
        self.assertIn('observe-2499',retained);self.assertIn('propose-30',retained)
        measured=retained['analyze-20']['observation']
        self.assertEqual(measured['measurement']['value'],40)
        self.assertTrue(measured['memory_detail_omitted'])
        changed=copy.deepcopy(rows);changed[0]['result']['reserved_gpu_hours']=.6
        self.assertNotEqual(summary['full_context_sha256'],history_context(changed,4)[0]['observation']['full_context_sha256'])

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

    def test_context_versions_are_exact_supported_integers(self):
        for value in (True,False,1.0,4.0,'4',None,0,5):
            with self.assertRaisesRegex(ValueError,'Unsupported'):history_context([],value)
