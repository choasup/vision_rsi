"""Export and exercise an actual task's interface bundle without API or training."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from vision_rsi.runner import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-id',required=True)
    parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--root',default='runs/task-bundle-probes')
    args=parser.parse_args()
    sessions=Path(args.sessions).resolve()
    database=sessions/'sessions.sqlite3'
    before=database.read_bytes()
    folder=Path(args.root).resolve()/uuid.uuid4().hex
    folder.mkdir(parents=True)
    command=[sys.executable,'-X','utf8','-m','vision_rsi','training','build',
             '--session-id',args.session_id,'--sessions',str(sessions),
             '--offline','--output',str(folder/'bundles'),'--json']
    def build():
        run=subprocess.run(command,cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert run.returncode==0,run.stderr
        return json.loads(run.stdout)
    artifact=build();bundle=Path(artifact['directory'])
    contract=json.loads((bundle/'contract.json').read_text(encoding='utf-8'))
    atomic_json(folder/'sample.json',contract['example_input'])
    atomic_json(folder/'output.json',contract['example_output'])
    atomic_json(folder/'invalid-output.json',None)
    criteria=[('check',[],0,'interface_checked'),
              ('validate-input',['--input',str(folder/'sample.json')],0,'valid'),
              ('validate-output',['--input',str(folder/'output.json')],0,'valid'),
              ('validate-output',['--input',str(folder/'invalid-output.json')],1,None),
              ('infer',['--input',str(folder/'sample.json')],2,'blocked')]
    atomic_json(folder/'preregistered.json',{'session_id':args.session_id,'criteria':criteria,
                'scope':'Interface only; examples are not model outputs or quality evidence.'})
    results=[]
    with tempfile.TemporaryDirectory(prefix='vision-rsi-exported-') as external:
        for action,arguments,code,status in criteria:
            run=subprocess.run([sys.executable,'-I','-X','utf8',str(bundle/'harness.py'),action]+arguments,
                               cwd=external,capture_output=True,text=True,encoding='utf-8',timeout=30)
            result={'action':action,'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr}
            results.append(result)
            atomic_json(folder/'results.json',results)
            assert run.returncode==code,result
            if status is not None:
                report=json.loads(run.stdout)
                assert report['status']==status and report['model_available'] is False
    again=build()
    assert again['reused'] and again['bundle_id']==artifact['bundle_id']
    assert database.read_bytes()==before
    evidence={'passed':True,'session_id':args.session_id,'directory':str(folder),
              'bundle_id':artifact['bundle_id'],'bundle':str(bundle),'reused_on_rebuild':True,
              'session_database_unchanged':True,'session_database_sha256':hashlib.sha256(before).hexdigest(),
              'isolated_process_checks':len(criteria),'llm_called':False,'remote_called':False,
              'training_performed':False,'model_quality_verified':False}
    atomic_json(folder/'evidence.json',evidence)
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
