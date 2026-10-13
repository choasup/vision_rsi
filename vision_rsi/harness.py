"""Build immutable, standalone interface harnesses from training task contracts."""
import hashlib
import json
from pathlib import Path
import uuid

from .contracts import interface_issues
from .runner import revision,digest


def build(session, root):
    if session.get('pending_request'):raise ValueError('Resolve unprocessed task requirements before building a new harness')
    if not session['versions']: raise ValueError('No task interface defined')
    latest=session['versions'][-1];contract=latest['contract']
    if latest.get('review_required'):raise ValueError('Review pending requirements changes before building a new harness')
    blockers=interface_issues(contract)
    if blockers: raise ValueError('Interface needs repair: '+'; '.join(blockers))
    source=Path(__file__).with_name('contracts.py').read_text(encoding='utf-8-sig')
    runtime='import json, math, re\nfrom pathlib import Path\n'+source[source.index('TYPES ='):source.index('class Sessions:')]
    runner=r'''import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description='Contract-bound interface harness; no trained model attached')
    p.add_argument('action',choices=['check','validate-input','validate-output','infer'])
    p.add_argument('--input');p.add_argument('--output')
    a=p.parse_args()
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    identity=manifest['identity']
    if hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()!=manifest['bundle_id']:
        p.exit(1,'Interface bundle identity changed\n')
    if (identity['artifacts']!=manifest['artifacts'] or any(identity[key]!=manifest[key]
            for key in ('task_id','session_id','contract_version','contract_sha256'))):
        p.exit(1,'Interface manifest differs from identity\n')
    for name,expected in manifest['artifacts'].items():
        if name not in ('contract.json','interface_runtime.py','harness.py'):
            p.exit(1,'Unknown artifact\n')
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            p.exit(1,'Artifact integrity failure: '+name+'\n')
    from interface_runtime import validate_sample, validate_schema
    contract=json.loads((ROOT/'contract.json').read_text(encoding='utf-8'))
    try:
        if a.action=='check':
            validate_sample(contract,contract['example_input'])
            validate_schema(contract['output_schema'],contract['example_output'])
            result={'status':'interface_checked','model_available':False,'training_performed':False}
        else:
            value=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
            if a.action=='validate-output': validate_schema(contract['output_schema'],value)
            else: validate_sample(contract,value)
            result={'status':'blocked' if a.action=='infer' else 'valid','model_available':False}
            if a.action=='infer': result['reason']='No trained inference adapter attached; no prediction produced.'
        result.update(task_id=manifest['task_id'],contract_version=manifest['contract_version'])
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if a.output: Path(a.output).write_text(text+'\n',encoding='utf-8')
        print(text)
        return 2 if result['status']=='blocked' else 0
    except (ValueError,TypeError,KeyError,OSError) as error:
        p.exit(1,str(error)+'\n')
if __name__=='__main__': raise SystemExit(main())
'''
    contract_hash=hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    files={'contract.json':(json.dumps(contract,ensure_ascii=False,indent=2)+'\n').encode('utf-8'),
           'interface_runtime.py':runtime.encode('utf-8'),'harness.py':runner.encode('utf-8')}
    artifacts={name:hashlib.sha256(content).hexdigest() for name,content in files.items()}
    identity={'format_version':2,'task_id':session['task_id'],'session_id':session['session_id'],
              'contract_version':latest['version'],'contract_sha256':contract_hash,'artifacts':artifacts}
    bundle_id=digest(identity)
    name=session['task_id']+'-v'+str(latest['version'])+'-'+bundle_id[:12]
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    target=root/name
    if target.exists():
        manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        if (manifest.get('identity')!=identity or manifest.get('bundle_id')!=bundle_id
                or manifest.get('artifacts')!=artifacts):raise ValueError('Existing harness identity conflict')
        if any(manifest.get(key)!=identity[key] for key in ('task_id','session_id','contract_version','contract_sha256')):
            raise ValueError('Existing harness metadata conflict')
        for file,expected in manifest['artifacts'].items():
            if file not in ('contract.json','interface_runtime.py','harness.py') or hashlib.sha256((target/file).read_bytes()).hexdigest()!=expected:
                raise ValueError('Existing harness artifact changed; refusing overwrite')
        return {'status':'interface_harness_ready','directory':str(target),'bundle_id':bundle_id,'reused':True,'model_available':False}
    staging=root/('.building-'+uuid.uuid4().hex);staging.mkdir()
    try:
        for filename,content in files.items():(staging/filename).write_bytes(content)
        manifest={'task_id':session['task_id'],'session_id':session['session_id'],'contract_version':latest['version'],
                  'contract_sha256':contract_hash,'identity':identity,'bundle_id':bundle_id,
                  'git_revision':revision(),'status':'interface_only',
                  'execution_blockers':latest['issues']+['No training/inference model adapter'],
                  'artifacts':artifacts}
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        staging.rename(target)
    except Exception:
        # Preserve staging for inspection; never overwrite a prior harness.
        raise
    return {'status':'interface_harness_ready','directory':str(target),'bundle_id':bundle_id,'reused':False,'model_available':False,'training_performed':False}
