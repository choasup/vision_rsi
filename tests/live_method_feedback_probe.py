"""One explicit real API call on synthetic compiler feedback; never trains a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_experiments import ExperimentTests,proposal
from vision_rsi.experiments import propose_next
from vision_rsi.experiment_observe import inspect_request
from vision_rsi.llm_usage import snapshot
from vision_rsi.runner import atomic_json,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--root',default='runs/method-feedback-live')
    args=parser.parse_args()
    if not args.live:parser.error('Explicit --live required; at most one actual API admission, no GPU')
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))['llm']
    name=config.get('api_key_env')
    if os.name=='nt' and isinstance(name,str) and not os.environ.get(name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            if isinstance(value,str):os.environ[name]=value
    folder=Path(args.root).resolve()/uuid.uuid4().hex;folder.mkdir(parents=True)
    fixture=ExperimentTests();fixture.setUp()
    try:
        # Persist fixture inputs outside its temporary-directory lifetime.
        for field in ('plan_path','receipt_path'):
            source=Path(fixture.record['details'][field])
            target=folder/source.name;target.write_bytes(source.read_bytes())
            fixture.record['details'][field]=str(target)
        llm=dict(config,usage_ledger=str(folder/'usage.sqlite3'),usage_call_limit=1)
        invalid=proposal();invalid['recipe_changes']={'world_size':8}
        atomic_json(folder/'preregistered.json',{
            'fixture':True,'model':llm.get('model'),'max_actual_api_admissions':1,
            'synthetic_ap':42,'synthetic_gpu_budget':1,'parent_plan_id':fixture.record['plan_id'],
            'seed_proposal':invalid,'seed_is_mock_not_provider_response':True,
            'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].joinpath('vision_rsi').glob('*.py')},
            'pass_criteria':['seed rejected by compiler','real response compiles under original frozen constraints','cached replay makes no API call',
                             'snapshot hash verifies and includes rejection feedback',
                             'observation CLI matches read-only library and leaves request database unchanged'],
            'scope':'Development compiler-feedback probe; no measured training quality or research-efficiency claim.'})
        research=folder/'research'
        with patch('vision_rsi.llm.OpenAICompatibleClient') as mock_client:
            mock_client.return_value.complete.return_value={'content':json.dumps(invalid)}
            seed=propose_next(fixture.record,fixture.runs,llm,research,'synthetic-rejection')
        assert seed['status']=='proposal_rejected'
        atomic_json(folder/'seed-result.json',seed)
        result=None;failure=None;cached=False;observation=None;observed=False
        try:
            result=propose_next(fixture.record,fixture.runs,llm,research,'real-correction')
            with patch('vision_rsi.llm.OpenAICompatibleClient',side_effect=AssertionError('Replay must not call API')):
                cached=propose_next(fixture.record,fixture.runs,llm,research,'real-correction')==result
            database=research/'requests.sqlite3';before=database.read_bytes()
            observation=inspect_request(research,'real-correction',True)
            saved=json.loads((research/'real-correction'/'request.json').read_text(encoding='utf-8'))
            assert observation['snapshot_hash_verified'] and observation['request_snapshot']==saved['snapshot']
            prompt=json.loads(observation['request_snapshot']['messages'][1]['content'])
            assert prompt['previous_rejections'][0]['request_id']=='synthetic-rejection'
            command=subprocess.run([sys.executable,'-X','utf8','-m','vision_rsi','experiment-request',
                                    '--store',str(research),'--request-id','real-correction','--messages'],
                                   cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert command.returncode==0
            assert json.loads(command.stdout)==observation
            assert database.read_bytes()==before
            atomic_json(folder/'observation.json',observation)
            observed=True
        except Exception as error:
            failure=type(error).__name__  # Do not echo provider/config exception text.
        usage=snapshot(str(folder/'usage.sqlite3')) if (folder/'usage.sqlite3').exists() else None
        evidence={'directory':str(folder),'fixture':True,'passed':bool(result and result.get('status')=='ready_to_submit' and cached and observed),
                  'seed_rejected':True,'real_result_status':result.get('status') if result else None,
                  'real_result':result,'cached_replay_equal':cached,'failure_type':failure,'usage':usage,
                  'observation_cli_verified':observed,'request_database_unchanged_by_observation':observed,
                  'request_snapshot_sha256':observation.get('request_snapshot_sha256') if observation else None,
                  'preregistration_sha256':digest(json.loads((folder/'preregistered.json').read_text(encoding='utf-8'))),
                  'training_performed':False,'remote_called':False,'gpu_used':False,
                  'semantic_retry':False,'scope':'One synthetic case, no independent statistical or task-quality evidence.'}
        atomic_json(folder/'evidence.json',evidence)
        print(json.dumps({key:value for key,value in evidence.items() if key!='real_result'},ensure_ascii=False,indent=2))
        return int(not evidence['passed'])
    finally:fixture.doCleanups()


if __name__=='__main__':raise SystemExit(main())
