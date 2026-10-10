import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.campaign import available,project
from vision_rsi.policy_audit import verify_trace
from vision_rsi.runner import digest


class PolicyAuditTests(unittest.TestCase):
    def test_baseline_rejects_skipped_phase_and_changed_decision(self):
        action=available({'history':[]})[0]
        row={'action':action,'status':'completed','decision':{'action_id':action['id'],'rationale':'Deterministic baseline control order'},'result':{'status':'blocked'}}
        state={'binding':{'policy':None},'history':[row]};project(state,row['action'],row['result'])
        self.assertTrue(verify_trace(state)['verified'])
        state['analysis']={'quality_verified':True}
        with self.assertRaisesRegex(ValueError,'projection'):verify_trace(state)
        state.pop('analysis')
        row['decision']['action_id']='submit-0'
        with self.assertRaises(ValueError):verify_trace(state)
        row['action']['kind']='submit'
        with self.assertRaises(ValueError):verify_trace(state)

    def test_candidate_request_context_output_and_source_are_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cid='a'*64;folder=root/cid;checkout=folder/'checkout'
            (checkout/'vision_rsi').mkdir(parents=True);(folder/'checks').mkdir()
            source=b'# frozen source\n';(checkout/'vision_rsi/research.py').write_bytes(source)
            record={'candidate_id':cid,'git_revision':'b'*40,'checkout':str(checkout),'source_hashes':{}}
            (folder/'candidate.json').write_text(json.dumps(record))
            policy={'store':str(root),'candidate_id':cid,'module':'vision_rsi.research'}
            actions=available({'history':[]});decision={'action_id':actions[0]['id'],'rationale':'Prepare first'}
            cases=[{'history':[],'actions':actions,'budget':3}]
            hashes={'vision_rsi/research.py':hashlib.sha256(source).hexdigest()}
            request={'files':{'vision_rsi/research.py':base64.b64encode(source).decode()},'source_hashes':hashes,'module':policy['module'],'function':'propose','cases':cases}
            report=dict(candidate_id=cid,git_revision=record['git_revision'],status='protocol_passed',protocol_failures=[],protocol_source_sha256='protocol',cases=cases,request_sha256=digest(request),response={'source_hashes':hashes,'observation':{'results':[decision]}})
            path=folder/'checks/one.protocol.json'
            row={'action':actions[0],'status':'completed','decision':decision,'result':{'status':'blocked'},'policy_evidence':str(path),'control_sources':{'strategy_protocol.py':'protocol'}}
            state={'binding':{'policy':policy},'history':[row]};project(state,row['action'],row['result'])
            with patch('vision_rsi.policy_audit.verify_candidate',return_value=record):
                path.write_text(json.dumps(report));self.assertTrue(verify_trace(state)['verified'])
                for field,value in [('candidate_id','c'*64),('request_sha256','0'*64),('protocol_source_sha256','changed')]:
                    original=report[field];report[field]=value;path.write_text(json.dumps(report))
                    with self.assertRaises(ValueError):verify_trace(state)
                    report[field]=original
                report['response']['observation']['results']=[{'action_id':None,'rationale':'Stop'}]
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):verify_trace(state)
                stop={'decision':{'action_id':None,'rationale':'Stop'},'policy_evidence':str(path),'control_sources':row['control_sources']}
                state={'binding':{'policy':policy},'history':[],'status':'policy_stopped','policy_stop':stop}
                self.assertEqual(verify_trace(state)['decisions_verified'],1)
                state.pop('policy_stop')
                with self.assertRaisesRegex(ValueError,'stop evidence missing'):verify_trace(state)

    def test_retrieved_page_is_recomputed_during_policy_replay(self):
        from vision_rsi.research_memory import retrieve_page
        from vision_rsi.strategy_context import history_context
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cid='a'*64;folder=root/cid;checkout=folder/'checkout'
            (checkout/'vision_rsi').mkdir(parents=True);(folder/'checks').mkdir()
            source=b'# frozen source\n';(checkout/'vision_rsi/research.py').write_bytes(source)
            record={'candidate_id':cid,'git_revision':'b'*40,'checkout':str(checkout),'source_hashes':{}}
            (folder/'candidate.json').write_text(json.dumps(record))
            policy={'store':str(root),'candidate_id':cid,'module':'vision_rsi.research'}
            hashes={'vision_rsi/research.py':hashlib.sha256(source).hexdigest()}
            state={'binding':{'policy':policy,'research_rounds':1},'history':[],'research_rounds':1}
            results=[{'status':'ready_to_submit'}, {'run_id':'run','status':'completed'},
                     {'run_id':'run','status':'completed'},
                     {'quality_verified':False,'acceptance_review':{'box_AP':40,'threshold':60,'error_summary':{'detail':'x'*200000}}}]
            for index in range(5):
                actions=available(state,memory=True)
                action=next(a for a in actions if a['kind']=='retrieve_memory') if index==4 else actions[0]
                decision={'action_id':action['id'],'rationale':'Fixture decision'}
                cases=[{'history':history_context(state['history'],4),'actions':actions,'budget':1}]
                request={'files':{'vision_rsi/research.py':base64.b64encode(source).decode()},'source_hashes':hashes,'module':policy['module'],'function':'propose','cases':cases}
                report=dict(candidate_id=cid,git_revision=record['git_revision'],status='protocol_passed',protocol_failures=[],protocol_source_sha256='protocol',cases=cases,request_sha256=digest(request),response={'source_hashes':hashes,'observation':{'results':[decision]}})
                path=folder/('checks/'+str(index)+'.protocol.json');path.write_text(json.dumps(report))
                result=retrieve_page(state['history'],action) if index==4 else results[index]
                row={'action':action,'status':'completed','decision':decision,'result':result,'policy_evidence':str(path),'control_sources':{'strategy_protocol.py':'protocol'},'strategy_context_version':4,'controller_action_version':2}
                project(state,action,result);state['history'].append(row)
            with patch('vision_rsi.policy_audit.verify_candidate',return_value=record):
                self.assertEqual(verify_trace(state)['decisions_verified'],5)
                state['history'][-1]['result']['text']='invented diagnosis'
                with self.assertRaisesRegex(ValueError,'Retrieved memory page'):verify_trace(state)
