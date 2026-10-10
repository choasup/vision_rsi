import unittest
from vision_rsi.research_memory import metric_memory


class MetricMemoryTests(unittest.TestCase):
    def records(self,index,score,dataset='d'):
        return [{'key':str(index),'kind':'action','payload':{'tool':'evaluate_contract'}},
                {'key':str(index)+':result','kind':'result','payload':{'action':str(index),'status':'completed',
                 'observation':{'candidate_id':str(index),'report_sha256':'r'*64,
                    'evaluation_identity':dict(contract_sha256='c'*64,dataset_sha256=dataset*64,evaluator_sha256='e'*64,gate_sha256='g'*64),
                    'metric_report':dict(event_micro_f1=score,threshold=.9,metric_threshold_met=score>=.9,tp=1,fp=1,fn=1)}}}]

    def test_best_and_latest_failure_survive_old_event_window(self):
        events=self.records(1,.95)+self.records(2,.2)
        events += [{'key':'noise'+str(i),'kind':'evidence','payload':{}} for i in range(30)]
        memory=metric_memory(events);group=memory['groups'][0]
        self.assertEqual(memory['evaluation_count'],2)
        self.assertEqual(group['best']['ref'],'1:result')
        self.assertEqual(group['latest_failure']['ref'],'2:result')
        self.assertFalse(memory['agent_adopted'])

    def test_different_data_are_not_ranked_together_and_group_count_is_bounded(self):
        events=self.records(1,.9,'a')+self.records(2,.1,'b')+self.records(3,.5,'c')
        memory=metric_memory(events)
        self.assertEqual(len(memory['groups']),2)
        self.assertEqual(memory['omitted_group_count'],1)
        self.assertEqual([g['best']['event_micro_f1'] for g in memory['groups']],[.5,.1])

    def test_unlinked_and_failed_results_are_not_metric_memory(self):
        records=self.records(1,.9)
        self.assertEqual(metric_memory(records[1:])['evaluation_count'],0)
        records[1]['payload']['status']='failed'
        self.assertEqual(metric_memory(records)['evaluation_count'],0)
