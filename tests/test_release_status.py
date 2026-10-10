import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from vision_rsi.contracts import Sessions
from vision_rsi.release_status import inspect


class ReleaseStatusTests(unittest.TestCase):
    def test_complete_local_evidence_never_claims_live_inference_or_rsi(self):
        from test_acceptance import evidence
        from vision_rsi.acceptance import review
        from vision_rsi.runner import digest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=Sessions(root/'sessions')
            session=store.create('fixture-task','COCO fixture audit')
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
            contract['acceptance'].update(metric='box_AP',threshold=60,direction='maximize')
            contract['acceptance']['evaluation_protocol']='COCO bbox AP'
            contract['inputs']={'image':{'type':'image','required':True}}
            contract['output_schema']={'type':'object','properties':{'detections':{'type':'array','items':{'type':'object','properties':{}}}}}
            contract['example_input']={'sample_id':'one','inputs':{'image':{'type':'image','uri':'image.jpg'}}}
            contract['example_output']={'detections':[]}
            contract['budget']={'gpu_hours':1};store.define(session['session_id'],contract)
            plan,receipt=evidence();plan.update(session_id=session['session_id'],task_id='fixture-task',contract=contract)
            receipt['run_id']='train-fixture';accepted=review(plan,receipt)
            version='b'*32;registry=root/'registry';path=registry/'fixture-task'/version;path.mkdir(parents=True)
            artifacts={'plan.json':json.dumps(plan).encode(),'receipt.json':json.dumps(receipt).encode(),'inference.py':b'# fixture, not executed'}
            serving={'backend':'cpu','protocol':'pycocotools.COCOeval/bbox/defaults','metric_scale':'0..100','pycocotools_version':'2.0.11',
                'checkpoint_sha256':accepted['checkpoint_sha256'],'training_identity_hash':digest(accepted['training_identity']),
                'serving_runtime_sha256':'9'*64,'inference_adapter_sha256':hashlib.sha256(artifacts['inference.py']).hexdigest(),
                'annotation_sha256':plan['recipe']['val_annotations_sha256'],'fixture':False,'image_count':5000,'coverage_complete':True,
                'metrics':{'box_AP':65},'predictions_sha256':'d'*64,'coverage_sha256':'e'*64}
            artifacts['serving-report.json']=json.dumps(serving).encode()
            manifest={'task_id':'fixture-task','version':version,'session_id':session['session_id'],'status':'validated','spec':{'kind':'coco_detection'},
                'training_run_id':'train-fixture','endpoint':{'contract':contract,'checkpoint_sha256':accepted['checkpoint_sha256'],
                'training_identity_hash':digest(accepted['training_identity']),'serving_runtime_sha256':'9'*64,'recipe':plan['recipe'],'source_hashes':plan['source_hashes']},
                'artifacts':{name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()}}
            for name,data in artifacts.items():(path/name).write_bytes(data)
            raw=json.dumps(manifest).encode();(path/'manifest.json').write_bytes(raw)
            with closing(sqlite3.connect(registry/'registry.sqlite3')) as db,db:
                db.execute('CREATE TABLE versions(task_id TEXT,version TEXT,status TEXT,manifest_hash TEXT,created INTEGER)')
                db.execute('INSERT INTO versions VALUES (?,?,?,?,1)',('fixture-task',version,'validated',hashlib.sha256(raw).hexdigest()))
            result=inspect(session['session_id'],store.root,registry)
            self.assertTrue(result['local_release_evidence_complete'])
            self.assertFalse(result['remote_availability_verified'])
            self.assertFalse(result['inference_executed'])
            self.assertFalse(result['rsi_efficiency_verified'])

    def test_missing_registry_is_not_created_and_fake_validated_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sessions=Sessions(root/'sessions')
            session=sessions.create('fixture-task','vision task')
            contract=json.loads((Path(__file__).resolve().parents[1]/'examples/interface-contract.json').read_text(encoding='utf-8'))
            sessions.define(session['session_id'],contract)
            before=(sessions.root/'sessions.sqlite3').read_bytes()
            registry=root/'registry'
            result=inspect(session['session_id'],sessions.root,registry)
            self.assertFalse(result['local_release_evidence_complete'])
            self.assertFalse(registry.exists())
            registry.mkdir();version='a'*32;path=registry/'fixture-task'/version;path.mkdir(parents=True)
            raw=json.dumps({'task_id':'fixture-task','version':version,'session_id':session['session_id'],'status':'validated','spec':{'kind':'coco_detection'},
                            'endpoint':{'contract':contract},'artifacts':{}}).encode()
            (path/'manifest.json').write_bytes(raw)
            with closing(sqlite3.connect(registry/'registry.sqlite3')) as db,db:
                db.execute('CREATE TABLE versions(task_id TEXT,version TEXT,status TEXT,manifest_hash TEXT,created INTEGER)')
                db.execute('INSERT INTO versions VALUES (?,?,?,?,1)',('fixture-task',version,'validated',hashlib.sha256(raw).hexdigest()))
            result=inspect(session['session_id'],sessions.root,registry)
            self.assertFalse(result['local_release_evidence_complete'])
            self.assertIn('artifact set',result['versions'][0]['blocker'])
            self.assertEqual(before,(sessions.root/'sessions.sqlite3').read_bytes())
            (path/'manifest.json').write_bytes(b'{}')
            result=inspect(session['session_id'],sessions.root,registry)
            self.assertIn('integrity failure',result['versions'][0]['blocker'])


if __name__=='__main__':unittest.main()
