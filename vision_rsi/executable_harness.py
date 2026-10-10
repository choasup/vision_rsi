"""Export frozen CLI controls while retaining the original durable task ledgers."""
import hashlib
import json
from pathlib import Path
import re
import uuid
import time

from .runner import digest


ENTRY=r'''import argparse,base64,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description='Frozen task controls; quality requires validated capability evidence')
    p.add_argument('mode',choices=['check','validate-input','validate-output','prepare-input','verify-input','decode-input','evaluate-events','training','test'])
    p.add_argument('--ground-truth');p.add_argument('--predictions')
    p.add_argument('--field')
    p.add_argument('--action',choices=['prepare','advance','watch','agent-status','agent-pause','agent-resume','status','logs','cancel','collect','resume','register','serving-evaluate','select-candidate','deliver-candidate','delivery-status','release-status'],default='prepare')
    p.add_argument('--dataset');p.add_argument('--max-latency-seconds',type=float)
    p.add_argument('--select-development',action='store_true')
    p.add_argument('--input');p.add_argument('--input-dir');p.add_argument('--samples-manifest');p.add_argument('--output');p.add_argument('--output-dir')
    p.add_argument('--version');p.add_argument('--run-id');p.add_argument('--campaign-id');p.add_argument('--steps',type=int,default=3)
    p.add_argument('--watch-seconds',type=float,default=3600);p.add_argument('--poll-seconds',type=float,default=15)
    p.add_argument('--research-rounds',type=int);p.add_argument('--resume',action='store_true')
    p.add_argument('--wall-seconds-budget',type=float);p.add_argument('--chunk-size',type=int,default=10)
    a=p.parse_args()
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    identity=manifest['identity']
    encoded=json.dumps(identity,sort_keys=True).encode()
    if hashlib.sha256(encoded).hexdigest()!=manifest['bundle_id']:p.exit(1,'Harness identity changed\n')
    expected=identity['artifacts']
    required={'harness.py','contract.json','interface_runtime.py','config.json','run.cmd'}
    if not required<=set(expected):p.exit(1,'Harness artifacts incomplete\n')
    for name,checksum in expected.items():
        if name not in required and not re.fullmatch(r'vision_rsi/[A-Za-z_][A-Za-z0-9_]*\.py',name):p.exit(1,'Invalid artifact name\n')
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:p.exit(1,'Harness artifact changed: '+name+'\n')
    actual={str(path.relative_to(ROOT)).replace('\\','/') for path in (ROOT/'vision_rsi').rglob('*') if path.is_file()}
    if actual!={name for name in expected if name.startswith('vision_rsi/')}:p.exit(1,'Unexpected runtime source\n')
    if (ROOT/'__pycache__').exists():p.exit(1,'Unexpected interface bytecode cache\n')
    sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
    contract=json.loads((ROOT/'contract.json').read_text(encoding='utf-8'))
    from interface_runtime import validate_sample,validate_schema
    try:
        if a.mode=='evaluate-events':
            if not a.ground_truth or not a.predictions or not a.output:
                raise ValueError('evaluate-events requires --ground-truth, --predictions and --output')
            from vision_rsi.event_eval import evaluate
            from vision_rsi.runner import atomic_json
            destination=Path(a.output).resolve()
            if destination.exists() or destination.is_relative_to(ROOT):
                raise ValueError('Evaluation output must be new and outside frozen harness')
            result=evaluate(a.ground_truth,a.predictions,contract_path=ROOT/'contract.json')
            result.update(task_id=identity['task_id'],contract_version=identity['contract_version'],
                          harness_bundle_id=manifest['bundle_id'])
            atomic_json(destination,result)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.mode=='decode-input':
            if not a.input or not a.output or not a.field:raise ValueError('decode-input requires --input packet.json --field video_field --output frames.json')
            from vision_rsi.media import decode_packet
            from vision_rsi.runner import atomic_json
            destination=Path(a.output).resolve()
            if destination.exists() or destination.is_relative_to(ROOT):raise ValueError('Decoded output must be new and outside frozen harness')
            with Path(a.input).open('rb') as stream:raw=stream.read(90*1024*1024+1)
            if len(raw)>90*1024*1024:raise ValueError('Media packet exceeds 90 MiB')
            result=decode_packet(contract,json.loads(raw.decode('utf-8-sig')),a.field,identity.get('video_decoders',{}).get(a.field),json.loads((ROOT/'config.json').read_text())['remote'])
            atomic_json(destination,result)
            print(json.dumps({k:v for k,v in result.items() if k!='frames'},ensure_ascii=False,indent=2));return 0
        if a.mode=='verify-input':
            if not a.input:raise ValueError('verify-input requires --input packet.json')
            from vision_rsi.media import verify_sample_request
            with Path(a.input).open('rb') as stream:raw=stream.read(90*1024*1024+1)
            if len(raw)>90*1024*1024:raise ValueError('Media packet exceeds 90 MiB')
            result=verify_sample_request(contract,json.loads(raw.decode('utf-8-sig')))
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.mode=='prepare-input':
            if not a.input or not a.output:raise ValueError('prepare-input requires --input sample.json and --output packet.json')
            from vision_rsi.media import sample_request
            from vision_rsi.runner import atomic_json
            packet=sample_request(contract,a.input)
            destination=Path(a.output).resolve()
            if destination==Path(a.input).resolve() or destination.is_relative_to(ROOT):raise ValueError('Output must not overwrite input or frozen harness artifacts')
            if destination.exists():raise ValueError('Packet output already exists')
            atomic_json(destination,packet)
            print(json.dumps({k:v for k,v in packet.items() if k not in ('sample','assets')},ensure_ascii=False,indent=2));return 0
        if a.mode in ('check','validate-input','validate-output'):
            if a.mode=='check':
                validate_sample(contract,contract['example_input']);validate_schema(contract['output_schema'],contract['example_output'])
                from vision_rsi.task_adapters import training_adapter
                from vision_rsi.contracts import EVENT_PROTOCOL
                result={'status':'executable_controls_checked','task_id':identity['task_id'],'contract_version':identity['contract_version'],
                        'training_performed':False,'model_quality_verified':False,'training_adapter':training_adapter(contract),
                        'evaluation_modes':['evaluate-events'] if contract.get('acceptance',{}).get('evaluation_protocol')==EVENT_PROTOCOL else [],
                        'shared_storage':identity['storage'],'video_decoders':identity.get('video_decoders',{})}
            else:
                if not a.input:raise ValueError('--input required')
                value=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
                if a.mode=='validate-input':validate_sample(contract,value)
                else:validate_schema(contract['output_schema'],value)
                result={'valid':True,'model_quality_verified':False}
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        import vision_rsi.runner as runtime
        runtime.revision=lambda:identity['git_revision']
        storage=identity['storage']
        if a.mode=='training':
            import os
            key_env=json.loads((ROOT/'config.json').read_text(encoding='utf-8')).get('llm',{}).get('api_key_env')
            if os.name=='nt' and key_env and not os.environ.get(key_env):
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as env:
                        value,_=winreg.QueryValueEx(env,key_env)
                        if isinstance(value,str):os.environ[key_env]=value
                except OSError:pass
            from vision_rsi.contracts import Sessions
            session=Sessions(storage['sessions']).show(identity['session_id'])
            latest=session['versions'][-1] if session['versions'] else {}
            if latest.get('version')!=identity['contract_version'] or latest.get('contract')!=contract or latest.get('review_required') or session['pending_request']:
                raise ValueError('Original task requirements changed or are pending; rebuild the harness')
            if a.run_id:
                from vision_rsi.training_runs import TrainingRuns
                runs=TrainingRuns(storage['runs'],read_only=True)
                try:
                    if runs.get(a.run_id)['session_id']!=identity['session_id']:raise ValueError('Run belongs to another task session')
                finally:runs.close()
            from vision_rsi.training_cli import main as training
            args=[a.action,'--session-id',identity['session_id'],'--sessions',storage['sessions'],'--run-store',storage['runs'],
                  '--campaign-store',storage['campaigns'],'--registry',storage['registry'],'--config',str(ROOT/'config.json'),'--json']
            if a.action=='prepare':args+=['--output',storage['plans']]
            if a.action in ('select-candidate','deliver-candidate'):
                if not storage.get('research'):raise ValueError('Harness requires explicit research storage; rebuild with the research directory')
                args+=['--research-root',storage['research']]
            if a.dataset:args+=['--dataset',a.dataset]
            if a.max_latency_seconds is not None:args+=['--max-latency-seconds',str(a.max_latency_seconds)]
            if a.select_development:args+=['--select-development']
            args+=['--steps',str(a.steps),'--watch-seconds',str(a.watch_seconds),'--poll-seconds',str(a.poll_seconds),'--chunk-size',str(a.chunk_size)]
            for flag,value in [('--run-id',a.run_id),('--campaign-id',a.campaign_id),('--research-rounds',a.research_rounds),('--version',a.version),('--wall-seconds-budget',a.wall_seconds_budget)]:
                if value is not None:args+=[flag,str(value)]
            if a.input:args+=['--sample',a.input]
            if a.action=='serving-evaluate':args+=['--task-id',identity['task_id']]
            training(args);return 0
        if not a.version:raise ValueError('Test requires an explicit validated --version')
        from vision_rsi.capability import Capabilities
        registry=Capabilities(storage['registry'])
        try:
            version=registry.resolve_version(identity['task_id'],a.version)
            manifest_path=Path(storage['registry'])/identity['task_id']/version/'manifest.json'
            capability=json.loads(manifest_path.read_text(encoding='utf-8'))
            if capability.get('spec',{}).get('kind')=='candidate_bundle':
                from vision_rsi.candidate_bundle import verify
                candidate=verify(manifest_path.parent/'bundle.json')
                capability_contract=json.loads(base64.b64decode(candidate['contract_base64']))
                if capability.get('session_id')!=identity['session_id']:raise ValueError('Candidate belongs to a different frozen harness session')
            else:capability_contract=capability.get('endpoint',{}).get('contract')
            if capability_contract!=contract:raise ValueError('Capability contract differs from frozen harness')
        finally:registry.close()
        args=['test','--task-id',identity['task_id'],'--version',a.version,'--registry',storage['registry']]
        for flag,value in [('--input',a.input),('--input-dir',a.input_dir),('--manifest',a.samples_manifest),('--output',a.output),('--output-dir',a.output_dir)]:
            if value is not None:args+=[flag,value]
        if a.resume:args+=['--resume']
        sys.argv=['harness.py']+args;runtime.main();return 0
    except (ValueError,KeyError,TypeError,OSError) as error:p.exit(1,str(error)+'\n')

if __name__=='__main__':raise SystemExit(main())
'''


def build_executable(session,interface,config,storage,root):
    required={'sessions','runs','campaigns','registry','plans'}
    if not required<=set(storage) or set(storage)-required-{'research'}:raise ValueError('Harness needs original shared storage locations')
    storage={key:str(Path(value).resolve()) for key,value in storage.items()}
    safe={'llm':{key:config.get('llm',{})[key] for key in ('model','base_url','api_key_env','thinking','usage_ledger','usage_call_limit') if key in config.get('llm',{})},
          'remote':{key:config.get('remote',{})[key] for key in ('ssh_host','ssh_port','workspace','python','coco_root') if key in config.get('remote',{})},
          'training':config.get('training',{})}
    from .controller_budget import configured_limit
    configured_limit(config)
    if 'controller' in config:safe['controller']=config['controller']
    allowed={'detector','epochs','batch_size_per_gpu','seed','checkpoint_steps','world_size','min_size','max_size','learning_rate','weight_decay','fixture','coco_root','weights','weights_sha256','train_annotations_sha256','val_annotations_sha256','acceptance_threshold','timeout_seconds'}
    if not isinstance(safe['training'],dict) or set(safe['training'])-allowed:raise ValueError('Unsupported training settings in harness')
    latest=session['versions'][-1];base=Path(interface['directory'])
    files={name:(base/name).read_bytes() for name in ('contract.json','interface_runtime.py')}
    files.update({'config.json':(json.dumps(safe,indent=2)+'\n').encode(),'harness.py':ENTRY.encode()})
    launcher='@echo off\r\nsetlocal\r\nset "HARNESS_PYTHON=%USERPROFILE%\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe"\r\nif exist "%HARNESS_PYTHON%" (\r\n    "%HARNESS_PYTHON%" -B -X utf8 "%~dp0harness.py" %*\r\n) else (\r\n    python -B -X utf8 "%~dp0harness.py" %*\r\n)\r\nexit /b %errorlevel%\r\n'
    files['run.cmd']=launcher.encode()
    files.update({'vision_rsi/'+path.name:path.read_bytes() for path in sorted(Path(__file__).parent.glob('*.py'))})
    original=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    from .video_runtime import compile_plan
    decoders={name:compile_plan(field['processing']) for name,field in latest['contract']['inputs'].items() if field['type']=='video'}
    identity={'task_id':session['task_id'],'session_id':session['session_id'],'contract_version':latest['version'],
              'git_revision':original['git_revision'],'storage':storage,'video_decoders':decoders,'artifacts':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}}
    bundle_id=digest(identity);target=Path(root).resolve()/('executable-'+bundle_id)
    manifest={'bundle_id':bundle_id,'identity':identity,'status':'executable_controls_only','model_quality_verified':False}
    if target.exists():
        if json.loads((target/'manifest.json').read_text(encoding='utf-8'))!=manifest:raise ValueError('Existing executable harness identity changed')
        for name,raw in files.items():
            if (target/name).read_bytes()!=raw:raise ValueError('Existing executable harness artifact changed')
    else:
        staging=target.parent/('.building-'+uuid.uuid4().hex);staging.mkdir()
        for name,raw in files.items():
            path=staging/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        # Windows antivirus/indexers can briefly hold a freshly written directory.
        # Retry only this local atomic publication, never execution or dispatch.
        for attempt in range(5):
            try:
                staging.rename(target)
                break
            except PermissionError:
                if target.exists() or attempt==4:raise
                time.sleep(.1*(attempt+1))
    return {'status':'executable_harness_ready','directory':str(target),'bundle_id':bundle_id,
            'training_performed':False,'model_quality_verified':False,'shared_storage':storage}
