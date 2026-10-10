import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from vision_rsi.research_watch import watch


class ResearchWatchTests(unittest.TestCase):
    def test_cli_exhausted_ledger_needs_no_llm_config(self):
        import subprocess
        import sys
        from vision_rsi.contracts import Sessions
        from vision_rsi.task_research import prepare
        from vision_rsi.ledger import Ledger
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sessions=Sessions(root/'sessions')
            session=sessions.create('watch-fixture','developer CLI fixture')
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
            sessions.define(session['session_id'],contract)
            session=sessions.show(session['session_id'])
            prepared=prepare(session,root/'research')
            ledger=Ledger(prepared['directory'])
            ledger.append('budget','evidence',{'summary':'fixture budget','record_type':'planning_budget','max_planning_requests':1})
            ledger.append('request','evidence',{'summary':'fixture attempt','record_type':'planning_request'})
            ledger.append('unsent','reflection',{'summary':'fixture unsent','record_type':'planning_not_dispatched','request_key':'request'})
            count=len(ledger.events())
            command=[sys.executable,'-X','utf8','-m','vision_rsi','training','research-watch',
                     '--sessions',str(sessions.root),'--session-id',session['session_id'],
                     '--research-root',str(root/'research'),'--config',str(root/'missing-config.json'),'--json']
            output=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(output.returncode,0,output.stderr)
            result=json.loads(output.stdout)
            self.assertEqual(result['watch']['stop_reason'],'planning_limit_exhausted')
            self.assertEqual(result['watch']['completed_steps'],0)
            self.assertEqual(len(ledger.events()),count)

    def state(self,folder,events=1,state='manual_step_available'):
        return {'directory':folder,'events':events,'research_status':{'state':state}}

    def test_stops_before_execution_on_uncertain_request(self):
        with tempfile.TemporaryDirectory() as folder:
            step=Mock()
            result=watch(step,lambda:self.state(folder,state='uncertain_api_request'))
            step.assert_not_called()
            self.assertEqual(result['watch']['stop_reason'],'uncertain_api_request')
            self.assertEqual(json.loads(Path(result['watch']['report_path']).read_text())['automatic_retries'],0)

    def test_rejection_stops_without_second_api_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            step=Mock(return_value={'execution':{'last_step_status':'planning_rejected'}})
            states=iter([self.state(folder),self.state(folder),self.state(folder,3),self.state(folder,3)])
            result=watch(step,lambda:next(states),turns=10)
            self.assertEqual(step.call_count,1)
            self.assertEqual(result['watch']['stop_reason'],'planning_rejected')

    def test_exception_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            step=Mock(side_effect=RuntimeError('must not leak secret error detail'))
            result=watch(step,lambda:self.state(folder))
            self.assertEqual(step.call_count,1)
            self.assertEqual(result['watch']['stop_reason'],'needs_attention')
            self.assertNotIn('secret',json.dumps(result))

    def test_turns_are_bounded_and_no_progress_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            count=[1]
            def step():count[0]+=1;return {'execution':{'last_step_status':'tool_completed'}}
            result=watch(step,lambda:self.state(folder,count[0]),turns=2)
            self.assertEqual(result['watch']['completed_steps'],2)
            self.assertEqual(result['watch']['stop_reason'],'turn_limit_reached')
            result=watch(lambda:{},lambda:self.state(folder),turns=2)
            self.assertEqual(result['watch']['stop_reason'],'no_progress')

    def test_invalid_bounds_fail_before_inspection(self):
        inspect=Mock()
        for kwargs in ({'turns':True},{'turns':0},{'duration':float('nan')},{'duration':0}):
            with self.assertRaises(ValueError):watch(Mock(),inspect,**kwargs)
        inspect.assert_not_called()
