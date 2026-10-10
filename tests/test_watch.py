from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.watch import watch


class Clock:
    def __init__(self):self.now=0
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)/'state.json';path.write_text('{}')
        self.waiting={'campaign_id':'a'*64,'state_path':str(path),'status':'waiting','run_id':'original-job',
                      'run_status':'running','history':[],'intent':None,'plan':{'status':'ready_to_submit'}}
        self.done=dict(self.waiting,status='needs_research',run_status='completed',receipt_collected=True,analysis={'quality_verified':False})
        self.clock=Clock()
        self.addCleanup(patch.stopall)
        patch('vision_rsi.watch.time.monotonic',self.clock.monotonic).start()
        patch('vision_rsi.watch.time.sleep',self.clock.sleep).start()
    def watch(self,**kwargs):return watch(lambda:{'session_id':'session'},lambda:{},duration=60,poll_seconds=5,**kwargs)

    @patch('vision_rsi.watch.advance')
    def test_pins_campaign_waits_and_finishes_without_restart(self,advance):
        advance.side_effect=[self.waiting,self.waiting,self.done]
        events=[];result=self.watch(on_update=events.append)
        self.assertEqual(result['watch']['stop_reason'],'no_pending_actions')
        self.assertEqual(result['run_id'],'original-job');self.assertEqual(len(events),3)
        self.assertTrue(Path(result['watch']['report_path']).is_file())
        for call in advance.call_args_list[1:]:self.assertEqual(call.args[-1],'a'*64)
        self.assertFalse(result['watch']['remote_job_cancelled'])

    @patch('vision_rsi.watch.advance')
    def test_observation_timeout_retries_same_handle_only(self,advance):
        uncertain=dict(self.waiting,status='action_uncertain',intent={'action':{'kind':'observe'}})
        advance.side_effect=[self.waiting,RuntimeError('SSH observation timeout'),uncertain,self.done]
        result=self.watch()
        self.assertEqual(result['watch']['observation_retries'],1)
        self.assertEqual(result['watch']['stop_reason'],'no_pending_actions')
        self.assertEqual(result['run_id'],'original-job')
        for call in advance.call_args_list[1:]:self.assertEqual(call.args[-1],'a'*64)

    @patch('vision_rsi.watch.advance')
    def test_uncertain_llm_is_not_automatically_retried(self,advance):
        uncertain=dict(self.waiting,status='action_uncertain',intent={'action':{'kind':'propose_experiment'}})
        advance.side_effect=[RuntimeError('API result uncertain'),uncertain]
        result=self.watch()
        self.assertEqual(result['watch']['stop_reason'],'needs_attention')
        self.assertEqual(result['watch']['observation_retries'],0);self.assertEqual(advance.call_count,2)

    @patch('vision_rsi.watch.advance')
    def test_repeated_observation_failure_stops_without_terminalizing_job(self,advance):
        uncertain=dict(self.waiting,status='action_uncertain',intent={'action':{'kind':'observe'}})
        advance.side_effect=[item for _ in range(4) for item in (RuntimeError('SSH unavailable'),uncertain)]
        result=self.watch()
        self.assertEqual(result['watch']['observation_retries'],3)
        self.assertEqual(result['watch']['stop_reason'],'needs_attention')
        self.assertEqual(result['run_status'],'running')
        self.assertFalse(result['watch']['remote_job_cancelled'])

    @patch('vision_rsi.watch.advance')
    def test_elapsed_supervision_does_not_mark_running_job_terminal(self,advance):
        advance.return_value=self.waiting
        result=watch(lambda:{},lambda:{},duration=6,poll_seconds=5)
        self.assertEqual(result['watch']['stop_reason'],'duration_elapsed')
        self.assertEqual(result['run_status'],'running');self.assertFalse(result['watch']['remote_job_cancelled'])
        self.assertEqual(advance.call_count,2)

    @patch('vision_rsi.watch.advance')
    def test_pause_lost_worker_and_keyboard_interrupt_preserve_state(self,advance):
        for state,reason in [(dict(self.waiting,paused=True),'paused'),(dict(self.waiting,run_status='lost'),'remote_worker_lost_reservation_retained')]:
            advance.return_value=state;result=self.watch();self.assertEqual(result['watch']['stop_reason'],reason)
        advance.side_effect=[KeyboardInterrupt(),self.waiting]
        result=self.watch();self.assertEqual(result['watch']['stop_reason'],'interrupted')
        self.assertFalse(result['watch']['remote_job_cancelled'])

    def test_invalid_bounds_rejected(self):
        for kwargs in ({'duration':0},{'duration':float('nan')},{'poll_seconds':1},{'duration':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):watch(lambda:{},lambda:{},**kwargs)
