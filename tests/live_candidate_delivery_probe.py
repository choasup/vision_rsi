"""Bounded real CPU delivery fixture, never learned-model quality evidence."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.runner import atomic_json
from vision_rsi.candidate_bundle import verify,build
from vision_rsi.bundle_evaluation import evaluate_bundle
from vision_rsi.contracts import Sessions
from vision_rsi.task_research import prepare
from vision_rsi.controller import bind_validation
from vision_rsi.ledger import Ledger
from vision_rsi.capability import Capabilities
from vision_rsi.research_history import accept
from vision_rsi.candidate_serving import check
from vision_rsi.candidate_delivery import promote
from vision_rsi.batch import batch,input_rows
import vision_rsi.remote as transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true')
    parser.add_argument('--bundle',required=True)
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--workflow',action='store_true',help='Use the integrated delivery workflow for fresh execution')
    args=parser.parse_args()
    if not args.live_remote:parser.error('Require --live-remote; at most six CPU calls, no LLM/GPU')
    repo=Path(__file__).resolve().parents[1]
    bundle=verify(args.bundle)
    contract=json.loads(base64.b64decode(bundle['contract_base64']))
    if bundle['identity'].get('media_transport')!='vision_sample_transport_v1':
        parser.error('Require a media transport bundle')
    remote=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))['remote']
    root=repo/'runs/candidate-delivery-live'/uuid.uuid4().hex
    root.mkdir(parents=True);print(str(root),flush=True)
    atomic_json(root/'preregistered.json',{'scope':__doc__,'max_remote_calls':6,'gpu_used':False,'llm_calls':0,
                'bundle_id':bundle['bundle_id'],'integrated_workflow':args.workflow,'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'criteria':['real isolated CPU execution','sealed ledger acceptance','immutable promotion',
                            'formal single and joint batch inference','cached external-directory CLI reuse']})
    original=transport.check_candidate;calls=[];registry=None;passed=False;failure=None
    def counted(*values):
        if len(calls)>=6:raise RuntimeError('Probe CPU call ceiling reached')
        calls.append(True);return original(*values)
    transport.check_candidate=counted
    try:
        sessions=Sessions(root/'sessions')
        session=sessions.create('delivery-fixture','Fixed developer CPU fixture; not learned visual quality')
        session=sessions.define(session['session_id'],contract)
        research_root=root/'research';prepared=prepare(session,research_root)
        folder=Path(prepared['directory']);ledger=Ledger(folder)
        # Reassemble verified source bytes against this session's exact frozen
        # contract, rather than silently relaxing the byte identity check.
        class VerifiedSources:
            def source_files(self,candidate_id):
                if candidate_id!=bundle['identity']['candidate_id']:raise ValueError('Source identity differs')
                return {'git_revision':bundle['identity']['git_revision']},{
                    name:base64.b64decode(value,validate=True) for name,value in bundle['files'].items()}
        assembled=build(VerifiedSources(),bundle['identity']['candidate_id'],bundle['identity']['module'],
                        bundle['identity']['function'],folder/'contract.json',folder/'bundles',media_input=True,
                        decode_video=bool(bundle['identity'].get('video_decoders')))
        bundle_path=assembled['path']
        atomic_json(root/'assembled.json',{'source_bundle_id':bundle['bundle_id'],'frozen_task_bundle':assembled})
        samples=[]
        for index,split in enumerate(('development','holdout','new-input')):
            sample=json.loads(json.dumps(contract['example_input']));sample['sample_id']=split
            for name,value in sample['inputs'].items():
                if value['type']=='text':continue
                for item_index,item in enumerate(value['items'] if value['type']=='image_list' else [value]):
                    filename=split+'-'+name+str(item_index)+'.bin';item['uri']=filename
                    content=b'P6\n1 1\n255\n'+bytes([item_index,index,250-index]) if value['type'] in ('image','image_list') else (split+' undecoded video fixture').encode()
                    (folder/filename).write_bytes(content)
            samples.append(sample)
        event={'label':'action','start_seconds':0,'end_seconds':1}
        def dataset(sample,purpose):
            return {'purpose':purpose,'samples':[sample],'ground_truth':{'labels':['action'],
                    'samples':[{'sample_id':sample['sample_id'],'events':[event]}]}}
        development=folder/'development.json';atomic_json(development,dataset(samples[0],'development_validation'))
        holdout=folder/'holdout.json';atomic_json(holdout,dataset(samples[1],'independent_acceptance'))
        bind_validation(ledger,{'research':{'task_contract':prepared['task_contract'],
            'validation_dataset':{'path':str(development),'sha256':hashlib.sha256(development.read_bytes()).hexdigest()},
            'candidate_bundle_execution':{'media_input':True,'decode_video':False}}})
        ledger.append('evaluate','action',{'summary':'Real CPU fixture development evaluation','tool':'evaluate_contract','executor':'research-v1'})
        report=evaluate_bundle(bundle_path,development,remote,folder/'bundle-evaluations')
        ledger.append('evaluate:result','result',{'summary':'Actual CPU fixture observation','action':'evaluate','status':'completed',
            'observation':{'report_path':report['report_path'],'report_sha256':hashlib.sha256(Path(report['report_path']).read_bytes()).hexdigest(),
                           'evaluation_identity':report['identity']}})
        ledger.append('pause','paused',{'summary':'Developer fixture research ended'})
        registry=Capabilities(root/'registry');candidate=registry.register_candidate(session,bundle_path)
        workflow=None
        if args.workflow:
            from vision_rsi.candidate_workflow import deliver
            workflow=deliver(registry,session,candidate['version'],holdout,research_root,remote,30)
            assert workflow['status']=='scoped_delivery_ready_for_test' and len(calls)==4
            assert deliver(registry,session,candidate['version'],holdout,research_root,remote,30)==workflow
            delivery=json.loads((registry.root/session['task_id']/workflow['version']/'manifest.json').read_text(encoding='utf-8'))
        else:
            acceptance=accept(registry,session,candidate['version'],holdout,remote,research_root)
            assert acceptance['status']=='holdout_metric_met'
            serving=check(registry,session,candidate['version'],holdout,remote,30)
            assert serving['status']=='serving_contract_checks_met' and len(calls)==4
            delivery=promote(registry,session,candidate['version'],research_root,remote)
        assert promote(registry,session,candidate['version'],research_root,remote)==delivery
        single=folder/'single.json';atomic_json(single,samples[2])
        output=registry.infer(session['task_id'],single)
        assert output['version']==delivery['version'] and output['output']=={'events':[event]} and len(calls)==5
        assert registry.infer(session['task_id'],single)==output and len(calls)==5
        manifest=folder/'batch.jsonl'
        manifest.write_text(json.dumps(dict(samples[2],sample_id='joint-batch'))+'\n',encoding='utf-8')
        summary=batch(registry,session['task_id'],input_rows(manifest=manifest),root/'batch-output')
        assert summary['succeeded']==1 and len(calls)==6
        assert batch(registry,session['task_id'],input_rows(manifest=manifest),root/'batch-output',resume=True)==summary
        for command,expected in [
            (['test','--task-id',session['task_id'],'--input',str(single),'--registry',str(registry.root)],output),
            (['training','promote-candidate','--session-id',session['session_id'],'--version',candidate['version'],
              '--sessions',str(sessions.root),'--research-root',str(research_root),'--registry',str(registry.root),
              '--config',str(Path(args.config).resolve())],delivery)]:
            completed=subprocess.run([sys.executable,'-X','utf8',str(repo/'launch_agent.py'),'--cli']+command,
                                     cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
            assert completed.returncode==0,completed.stderr
            assert json.loads(completed.stdout)==expected
        assert not output['acceptance']['production_accepted']
        from vision_rsi.release_status import inspect
        status=inspect(session['session_id'],sessions.root,registry.root)
        assert status['local_release_evidence_complete'] and not status['production_accepted']
        command=['training','release-status','--session-id',session['session_id'],'--sessions',str(sessions.root),
                 '--registry',str(registry.root),'--json']
        completed=subprocess.run([sys.executable,'-X','utf8',str(repo/'launch_agent.py'),'--cli']+command,
                                 cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
        assert completed.returncode==0,completed.stderr
        assert json.loads(completed.stdout)==status
        if args.workflow:
            command=['training','deliver-candidate','--session-id',session['session_id'],'--version',candidate['version'],
                     '--sessions',str(sessions.root),'--research-root',str(research_root),'--registry',str(registry.root),
                     '--dataset',str(holdout),'--max-latency-seconds','30','--config',str(Path(args.config).resolve())]
            completed=subprocess.run([sys.executable,'-X','utf8',str(repo/'launch_agent.py'),'--cli']+command,
                                     cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
            assert completed.returncode==0,completed.stderr
            assert json.loads(completed.stdout)==workflow
        assert len(calls)==6
        atomic_json(root/'delivery-result.json',{'delivery':delivery,'single':output,'batch':summary,'release_status':status,'workflow':workflow})
        passed=True
    except Exception as error:
        failure=type(error).__name__+': '+str(error)
        raise
    finally:
        transport.check_candidate=original
        if registry is not None:registry.close()
        atomic_json(root/'evidence.json',{'passed':passed,'failure':failure,'remote_calls':len(calls),'integrated_workflow':args.workflow,
            'llm_calls':0,'gpu_used':False,'quality_verified':False,'production_accepted':False,
            'scope':__doc__})


if __name__=='__main__':main()
