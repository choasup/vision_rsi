"""Build immutable, standalone interface harnesses from training task contracts."""
import hashlib
import json
from pathlib import Path
import uuid

from .contracts import issues
from .runner import revision


def build(session, root):
    if session.get('pending_request'):raise ValueError('Resolve unprocessed task requirements before building a new harness')
    if not session['versions']: raise ValueError('No task interface defined')
    latest=session['versions'][-1];contract=latest['contract']
    if latest.get('review_required'):raise ValueError('Review pending requirements changes before building a new harness')
    blockers=[x for x in issues(contract) if '预算' not in x and not x.startswith('待澄清:')]
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
    identity=hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    name=session['task_id']+'-v'+str(latest['version'])+'-'+identity[:12]
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    target=root/name
    if target.exists():
        manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        if manifest['contract_sha256']!=identity: raise ValueError('Existing harness contract conflict')
        for file,expected in manifest['artifacts'].items():
            if file not in ('contract.json','interface_runtime.py','harness.py') or hashlib.sha256((target/file).read_bytes()).hexdigest()!=expected:
                raise ValueError('Existing harness artifact changed; refusing overwrite')
        return {'status':'interface_harness_ready','directory':str(target),'reused':True,'model_available':False}
    staging=root/('.building-'+uuid.uuid4().hex);staging.mkdir()
    try:
        (staging/'contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (staging/'interface_runtime.py').write_text(runtime,encoding='utf-8')
        (staging/'harness.py').write_text(runner,encoding='utf-8')
        manifest={'task_id':session['task_id'],'session_id':session['session_id'],'contract_version':latest['version'],
                  'contract_sha256':identity,'git_revision':revision(),'status':'interface_only',
                  'execution_blockers':latest['issues']+['No training/inference model adapter'],
                  'artifacts':{f:hashlib.sha256((staging/f).read_bytes()).hexdigest() for f in ('contract.json','interface_runtime.py','harness.py')}}
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        staging.rename(target)
    except Exception:
        # Preserve staging for inspection; never overwrite a prior harness.
        raise
    return {'status':'interface_harness_ready','directory':str(target),'reused':False,'model_available':False,'training_performed':False}
