"""Exercise the frozen standalone entry point against validated generic fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_candidate_delivery as fixtures
from vision_rsi.executable_harness import build_executable
from vision_rsi.harness import build


class ExportedCandidateTests(unittest.TestCase):
    setUp=fixtures.CandidateDeliveryTests.setUp
    history=fixtures.CandidateDeliveryTests.history
    ready=fixtures.CandidateDeliveryTests.ready

    def command(self, folder, *args):
        return subprocess.run([sys.executable,'-B','-X','utf8',str(folder/'harness.py'),*args],
                              cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)

    @patch('vision_rsi.remote.check_candidate')
    def test_exported_generic_test_and_release_status_use_saved_evidence(self,remote):
        delivery=self.ready(remote)
        expected=self.registry.infer(self.session['task_id'],self.input)
        calls=remote.call_count
        storage={key:str(self.root/key) for key in ('sessions','runs','campaigns','registry','plans')}
        storage['registry']=str(self.registry.root)
        storage['research']=str(self.research_root)
        interface=build(self.session,self.root/'export')
        artifact=build_executable(self.session,interface,{'remote':{}},storage,self.root/'export')
        folder=Path(artifact['directory'])
        result=self.command(folder,'test','--version',delivery['version'],'--input',str(self.input))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),expected)
        status=self.command(folder,'training','--action','release-status','--version',delivery['version'])
        self.assertEqual(status.returncode,0,status.stderr)
        self.assertEqual(remote.call_count,calls)
        # A same-contract task from another session cannot be used by this export.
        manifest=self.registry.root/self.session['task_id']/delivery['version']/'manifest.json'
        saved=manifest.read_bytes()
        changed=json.loads(saved);changed['session_id']='different-session'
        manifest.write_text(json.dumps(changed))
        rejected=self.command(folder,'test','--version',delivery['version'],'--input',str(self.input))
        self.assertNotEqual(rejected.returncode,0)
        manifest.write_bytes(saved)

    @patch('vision_rsi.remote.check_candidate')
    def test_legacy_export_requires_explicit_research_storage_for_selection(self,remote):
        self.ready(remote)
        storage={key:str(self.root/key) for key in ('sessions','runs','campaigns','registry','plans')}
        storage['registry']=str(self.registry.root)
        interface=build(self.session,self.root/'export')
        artifact=build_executable(self.session,interface,{'remote':{}},storage,self.root/'export')
        result=self.command(Path(artifact['directory']),'training','--action','select-candidate')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('explicit research storage',result.stderr)
