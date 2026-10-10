import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.campaign import available
from vision_rsi.policy_audit import verify_trace
from vision_rsi.runner import digest


class PolicyAuditTests(unittest.TestCase):
    def test_baseline_rejects_skipped_phase_and_changed_decision(self):
        action=available({'history':[]})[0]
        row={'action':action,'status':'completed','decision':{'action_id':action['id'],'rationale':'Deterministic baseline control order'},'result':{'status':'blocked'}}
        state={'binding':{'policy':None},'history':[row]}
        self.assertTrue(verify_trace(state)['verified'])
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
            state={'binding':{'policy':policy},'history':[row]}
            with patch('vision_rsi.policy_audit.verify_candidate',return_value=record):
                path.write_text(json.dumps(report));self.assertTrue(verify_trace(state)['verified'])
                for field,value in [('candidate_id','c'*64),('request_sha256','0'*64),('protocol_source_sha256','changed')]:
                    original=report[field];report[field]=value;path.write_text(json.dumps(report))
                    with self.assertRaises(ValueError):verify_trace(state)
                    report[field]=original
                report['response']['observation']['results']=[{'action_id':None,'rationale':'Stop'}]
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):verify_trace(state)
