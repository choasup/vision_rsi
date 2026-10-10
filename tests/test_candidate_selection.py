import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_research_history as fixtures
from vision_rsi.candidate_selection import select


class CandidateSelectionTests(unittest.TestCase):
    setUp=fixtures.ResearchHistoryTests.setUp
    history=fixtures.ResearchHistoryTests.history

    @patch('vision_rsi.remote.check_candidate')
    def test_unmet_development_does_not_register_a_selected_candidate(self,remote):
        from vision_rsi.bundle_evaluation import evaluate_bundle
        def failed_evaluation(*args,**kwargs):
            base=remote.side_effect
            def missed(*values):
                result=base(*values)
                result['observation']['results']=[{'events':[]} for _ in values[1]['cases']]
                return result
            remote.side_effect=missed
            return evaluate_bundle(*args,**kwargs)
        with patch('test_research_history.evaluate_bundle',side_effect=failed_evaluation):
            self.history(remote)
        with self.assertRaisesRegex(ValueError,'No development candidate meets'):
            select(self.registry,self.session,self.research_root)
        self.assertFalse((self.folder/'candidate-selection.json').exists())
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_highest_recomputed_score_and_stable_bundle_tie_break(self,remote):
        import hashlib
        from vision_rsi.runner import atomic_json,digest
        from vision_rsi.bundle_evaluation import evaluate_bundle
        self.history(remote);original=remote.side_effect
        self.ledger.append('resume-more','resumed',{'summary':'Additional development fixture evaluations'})
        expected=[self.bundle['bundle_id']]
        for index,score in enumerate((0,1)):
            value=json.loads(Path(self.bundle['path']).read_text())
            value['identity']['candidate_id']=str(index+1)*64
            value['bundle_id']=digest(value['identity'])
            path=self.folder/'bundles'/value['bundle_id']/'bundle.json';path.parent.mkdir()
            atomic_json(path,value)
            def response(*args,hit=score):
                result=original(*args)
                if not hit:result['observation']['results']=[{'events':[]} for _ in args[1]['cases']]
                return result
            remote.side_effect=response
            report=evaluate_bundle(path,self.folder/'development.json',{},self.folder/'bundle-evaluations')
            action='extra-'+str(index)
            self.ledger.append(action,'action',{'summary':'Additional fixture evaluation','tool':'evaluate_contract','executor':'research-v1'})
            self.ledger.append(action+':result','result',{'summary':'Additional measured fixture','action':action,'status':'completed',
                'observation':{'report_path':report['report_path'],'report_sha256':hashlib.sha256(Path(report['report_path']).read_bytes()).hexdigest(),
                               'evaluation_identity':report['identity']}})
            if score:expected.append(value['bundle_id'])
        self.ledger.append('pause-more','paused',{'summary':'Additional development ended'})
        result=select(self.registry,self.session,self.research_root)
        self.assertEqual(result['selection']['selected']['bundle_id'],min(expected))
        self.assertEqual([row['event_micro_f1'] for row in result['selection']['ranked']],[1,1,0])
        self.assertEqual(remote.call_count,3)

    @patch('vision_rsi.remote.check_candidate')
    def test_selects_covered_development_and_cli_restores_without_dispatch(self,remote):
        self.history(remote)
        from vision_rsi.capability import Capabilities
        self.registry=Capabilities(self.root/'selected-registry');self.addCleanup(self.registry.close)
        self.assertEqual(self.registry.list(),[])
        result=select(self.registry,self.session,self.research_root)
        self.assertEqual(result['version'],self.delivery['version'])
        self.assertEqual(result['selection']['selected']['event_micro_f1'],1)
        self.assertFalse(result['holdout_used'])
        self.assertEqual(len(self.registry.list()),1)
        self.assertEqual(select(self.registry,self.session,self.research_root),result)
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'launch_agent.py'),'--cli',
                 'training','select-candidate','--session-id',self.session['session_id'],
                 '--sessions',str(self.root/'sessions'),'--research-root',str(self.research_root),'--registry',str(self.registry.root)]
        completed=subprocess.run(command,cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_changed_media_refuses_selection(self,remote):
        self.history(remote)
        dataset=json.loads((self.folder/'development.json').read_text())
        value=next(iter(dataset['samples'][0]['inputs'].values()))
        item=value['items'][0] if value['type']=='image_list' else value
        (self.folder/item['uri']).write_bytes(b'different actual media')
        with self.assertRaisesRegex(ValueError,'media changed'):
            select(self.registry,self.session,self.research_root)
        self.assertFalse((self.folder/'candidate-selection.json').exists())
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_rehashed_report_cannot_invent_a_development_score(self,remote):
        from vision_rsi.bundle_evaluation import evaluate_bundle
        from vision_rsi.runner import atomic_json
        def incorrect_report(*args,**kwargs):
            report=evaluate_bundle(*args,**kwargs)
            report['metric_report']['tp']+=1
            path=Path(report['report_path']);saved=json.loads(path.read_text())
            saved['metric_report']=report['metric_report'];atomic_json(path,saved)
            return report
        # The controller records the incorrect report's actual hash. Recompute
        # must reject it even though ledger/report identity checks pass.
        with patch('test_research_history.evaluate_bundle',side_effect=incorrect_report):
            self.history(remote)
        with self.assertRaisesRegex(ValueError,'metric differs from recomputed'):
            select(self.registry,self.session,self.research_root)
        self.assertEqual(remote.call_count,1)

    @patch('vision_rsi.remote.check_candidate')
    def test_first_selection_after_holdout_reservation_is_forbidden(self,remote):
        from vision_rsi.research_history import accept
        self.history(remote)
        accept(self.registry,self.session,self.delivery['version'],self.holdout,{},self.research_root)
        with self.assertRaisesRegex(ValueError,'post-holdout'):
            select(self.registry,self.session,self.research_root)
        self.assertEqual(remote.call_count,2)
