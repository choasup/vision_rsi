import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision_rsi.controller import research_step, observation_context
from vision_rsi.detector import COCO_IDS
from vision_rsi.ledger import Ledger
from vision_rsi.research_baseline import inspect,bind,arguments


class ResearchBaselineTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.contract={'inputs':{'image':{'type':'image','required':True}},'acceptance':{'metric':'box_AP','direction':'maximize',
            'evaluation_protocol':'COCO bbox AP','threshold':60},'output_schema':{'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}}}
        self.report={'protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100','pycocotools_version':'2.0.11',
            'coverage_complete':True,'image_count':5000,'annotation_sha256':'a'*64,'predictions_sha256':'b'*64,'coverage_sha256':'c'*64,
            'category_ids':list(COCO_IDS),'metrics':dict.fromkeys(('box_AP','AP50','AP75','AP_small','AP_medium','AP_large'),42)}
        self.metrics=self.root/'metrics.json';self.receipt=self.root/'receipt.json';self.path=self.root/'contract.json'
        self.path.write_text(json.dumps(self.contract))
        self.state={'status':'evaluated','coco_evaluated':True,'gpu_used':False,'training_started':False,
            'processed_images':5000,'total_images':5000,'identity':'d'*64}
        self.config={'llm':{'model':'fixture'},'research':{'task_contract':{'path':str(self.path),'sha256':self.sha(self.path)}}}
        self.write()

    def sha(self,path):return hashlib.sha256(path.read_bytes()).hexdigest()

    def write(self):
        self.metrics.write_text(json.dumps(self.report));self.state['metrics_sha256']=self.sha(self.metrics)
        self.receipt.write_text(json.dumps({'state':self.state,'report':self.report}))
        self.config['research']['baseline_evidence']={'receipt':str(self.receipt),'sha256':self.sha(self.receipt),
            'metrics':str(self.metrics),'metrics_sha256':self.sha(self.metrics),'annotation_sha256':'a'*64}

    def test_target_uses_current_contract_not_producer_claim(self):
        self.report['acceptance']={'threshold':1,'passed':True};self.write()
        result=inspect(self.config,self.contract)
        self.assertEqual(result['metric_gap'],18);self.assertFalse(result['observed_metric_target_met'])
        self.assertFalse(result['quality_verified']);self.assertFalse(result['remote_called'])
        self.assertEqual(observation_context(result)['metrics']['box_AP'],42)

    def test_incomplete_coverage_bad_metric_and_incompatible_contract_refused(self):
        for key,value in [('image_count',12),('coverage_complete',False),('category_ids',[1]),('pycocotools_version','wrong')]:
            original=self.report[key];self.report[key]=value;self.write()
            with self.assertRaises(ValueError):inspect(self.config,self.contract)
            self.report[key]=original
        self.write();other=copy.deepcopy(self.contract);other['acceptance']['metric']='F1'
        with self.assertRaisesRegex(ValueError,'incompatible'):inspect(self.config,other)
        self.metrics.write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):inspect(self.config,self.contract)

    def test_binding_cannot_change_or_be_removed_and_model_has_no_path_arguments(self):
        ledger=Ledger(self.root/'research');ledger.append('goal','objective',{'summary':'Task research'})
        first=bind(ledger,self.config,self.contract,'e'*64)
        self.assertEqual(bind(ledger,self.config,self.contract,'e'*64),first)
        with self.assertRaisesRegex(ValueError,'cannot be removed'):bind(ledger,{'research':{}})
        with self.assertRaisesRegex(ValueError,'frozen'):bind(ledger,self.config,self.contract,'f'*64)
        with self.assertRaises(ValueError):arguments({'path':'secret'})

    @patch('vision_rsi.controller.OpenAICompatibleClient')
    def test_controller_reads_baseline_then_cites_it_in_synthesis(self,client):
        ledger=Ledger(self.root/'research');ledger.append('goal','objective',{'summary':'Plan against measured task gap'})
        client.return_value.complete.return_value={'content':json.dumps({'tool':'read_baseline','summary':'Read baseline',
            'question':'gap?','expected_evidence':'Measured AP','refs':[],
            'arguments':{'expected_receipt_sha256':self.sha(self.receipt)}})}
        research_step(self.config,ledger.directory)
        result=ledger.events()[-1];self.assertEqual(result['payload']['status'],'completed')
        self.assertEqual(result['payload']['observation']['metric_gap'],18)
        client.return_value.complete.return_value={'content':json.dumps({'tool':'synthesize','summary':'Gap',
            'question':'next?','expected_evidence':'Finding','refs':[result['key']],
            'arguments':{'findings':[{'statement':'Observed AP42 below target60','refs':[result['key']]}],
                'limitations':['Not a model ceiling proof'],'next_steps':['Inspect supported harness changes']}})}
        research_step(self.config,ledger.directory)
        self.assertEqual(ledger.events()[-1]['payload']['status'],'completed')
        prompt=json.loads(client.return_value.complete.call_args.args[0][0]['content'])
        self.assertIn('synthesize',prompt['available_tools'])
        self.assertEqual([row['observation']['metrics']['box_AP'] for row in prompt['history'] if row['observation'].get('kind')=='collected_cpu_baseline'],[42])
