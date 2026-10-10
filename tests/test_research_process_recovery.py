"""Real child-process termination with a simulated, never-networked planner."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from vision_rsi.controller import research_step
from vision_rsi.ledger import Ledger
from vision_rsi.research_state import snapshot
from vision_rsi.research_watch import watch


CHILD = '''
from pathlib import Path
import sys,time
from unittest.mock import patch
from vision_rsi.controller import research_step
folder=Path(sys.argv[1])
class PendingPlanner:
    def __init__(self,config):pass
    def validate_config(self):pass
    def complete(self,*args,**kwargs):
        (folder/'planner-entered').write_text('simulated planner; no network',encoding='utf-8')
        time.sleep(60)
        raise AssertionError('Parent should terminate this development child first')
with patch('vision_rsi.controller.OpenAICompatibleClient',PendingPlanner):
    research_step({'llm':{'model':'fixture'},'research':{'max_planning_requests':2}},folder,steps=1)
'''

CHILD_ACTION = '''
from pathlib import Path
import sys,time,json
from unittest.mock import patch
from vision_rsi.controller import research_step
folder=Path(sys.argv[1])
class Planner:
    def __init__(self,config):pass
    def validate_config(self):pass
    def complete(self,*args,**kwargs):
        return {'content':json.dumps({'tool':'inspect_repository','summary':'fixture inspect',
            'question':'q','expected_evidence':'readonly observation','refs':['goal']})}
def pending_tool(*args,**kwargs):
    (folder/'tool-entered').write_text('simulated read-only tool; no network',encoding='utf-8')
    time.sleep(60)
with patch('vision_rsi.controller.OpenAICompatibleClient',Planner),patch('vision_rsi.controller.execute',pending_tool):
    research_step({'llm':{'model':'fixture'},'research':{'max_planning_requests':1}},folder,steps=1)
'''


class ResearchProcessRecoveryTests(unittest.TestCase):
    def test_process_death_after_action_recovers_without_replanning(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'Read-only action process-death fixture'})
            with (folder/'child.log').open('wb') as log:
                child=subprocess.Popen([sys.executable,'-X','utf8','-c',CHILD_ACTION,str(folder)],stdout=log,stderr=log)
                try:
                    deadline=time.monotonic()+20
                    while not (folder/'tool-entered').is_file():
                        if child.poll() is not None:self.fail('Child stopped before action boundary')
                        if time.monotonic()>=deadline:self.fail('Child failed to reach action boundary')
                        time.sleep(0.05)
                    self.assertIsNone(child.poll())
                    child.kill();child.wait(timeout=10)
                finally:
                    if child.poll() is None:child.kill();child.wait(timeout=10)
            self.assertEqual(snapshot(ledger.events())['state'],'pending_action_recovery')
            with patch('vision_rsi.controller.OpenAICompatibleClient') as client,patch('vision_rsi.controller.execute',return_value={'fixture':True}) as execute:
                research_step({'llm':{'model':'fixture'}},folder)
                self.assertEqual(execute.call_count,1)
                research_step({'llm':{'model':'fixture'}},folder)
                self.assertEqual(execute.call_count,1)
                client.assert_not_called()
            events=ledger.events()
            self.assertEqual(len([e for e in events if e['kind']=='action']),1)
            self.assertEqual(len([e for e in events if e['kind']=='result']),1)
            self.assertEqual(snapshot(events)['state'],'planning_limit_exhausted')

    def test_process_death_preserves_request_releases_lock_and_prevents_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'Process interruption developer fixture; no real API'})
            with (folder/'child.log').open('wb') as log:
                child=subprocess.Popen([sys.executable,'-X','utf8','-c',CHILD,str(folder)],stdout=log,stderr=log)
                try:
                    deadline=time.monotonic()+20
                    while not (folder/'planner-entered').is_file():
                        if child.poll() is not None:
                            self.fail('Child exited before planner marker: '+(folder/'child.log').read_text(encoding='utf-8'))
                        if time.monotonic()>=deadline:self.fail('Development child did not reach the planning boundary')
                        time.sleep(0.05)
                    self.assertIsNone(child.poll())
                    # Terminate only the process object created above, never by name/PID discovery.
                    child.kill()
                    child.wait(timeout=10)
                finally:
                    if child.poll() is None:
                        child.kill();child.wait(timeout=10)
            before=ledger.events()
            self.assertEqual(len([e for e in before if e['payload'].get('record_type')=='planning_request']),1)
            self.assertFalse(any(e['payload'].get('record_type')=='planning_response' for e in before))
            self.assertEqual(snapshot(before)['state'],'uncertain_api_request')
            with patch('vision_rsi.controller.OpenAICompatibleClient') as client:
                # This also proves the killed child's controller lease is no longer held.
                with self.assertRaisesRegex(RuntimeError,'Uncertain API request'):
                    research_step({'llm':{'model':'fixture'}},folder)
                client.assert_not_called()
            self.assertEqual(ledger.events(),before)
            advance=Mock()
            def inspect():return {'directory':str(folder),'events':len(ledger.events()),'research_status':snapshot(ledger.events())}
            result=watch(advance,inspect,turns=2)
            advance.assert_not_called()
            self.assertEqual(result['watch']['stop_reason'],'uncertain_api_request')
            report=json.loads(Path(result['watch']['report_path']).read_text(encoding='utf-8'))
            self.assertEqual(report['completed_steps'],0)
            self.assertEqual(report['automatic_retries'],0)
