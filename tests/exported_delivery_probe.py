"""Recheck an exported harness against saved real CPU evidence, offline only."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.contracts import Sessions
from vision_rsi.executable_harness import build_executable
from vision_rsi.harness import build
from vision_rsi.runner import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-root',required=True)
    parser.add_argument('--output',default='runs/exported-delivery-probes')
    args=parser.parse_args()
    root=Path(args.saved_root).resolve()
    saved=json.loads((root/'delivery-result.json').read_text(encoding='utf-8'))
    delivery=saved['delivery']
    session=Sessions(root/'sessions',read_only=True).show(delivery['session_id'])
    manifest=json.loads((root/'registry'/session['task_id']/delivery['version']/'manifest.json').read_text(encoding='utf-8'))
    config={'remote':manifest['delivery']['remote']}
    output=Path(args.output).resolve()/uuid.uuid4().hex
    output.mkdir(parents=True)
    storage={key:str(root/key) for key in ('sessions','runs','campaigns','registry','plans','research')}
    artifact=build_executable(session,build(session,output),config,storage,output)
    folder=Path(artifact['directory'])
    # Import frozen sources first; all new candidate dispatch and network sockets fail.
    wrapper="""import runpy,sys
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
target=sys.argv[2];sys.argv=sys.argv[2:]
with patch('vision_rsi.remote.check_candidate',side_effect=RuntimeError('Offline probe forbids dispatch')),patch('socket.socket',side_effect=RuntimeError('Offline probe forbids network')):
    runpy.run_path(target,run_name='__main__')
"""
    records=[]
    commands=[['test','--version',delivery['version'],'--input',str(root/'research'/session['session_id']/'single.json')],
              ['training','--action','release-status','--version',delivery['version']],
              ['training','--action','delivery-status','--version',delivery['parent_version']],
              ['test','--version',delivery['version'],'--samples-manifest',str(root/'research'/session['session_id']/'batch.jsonl'),
               '--output-dir',str(root/'batch-output'),'--resume']]
    failure=None
    try:
        for command in commands:
            result=subprocess.run([sys.executable,'-B','-X','utf8','-c',wrapper,str(folder),str(folder/'harness.py'),*command],
                                  cwd=output,capture_output=True,text=True,encoding='utf-8',timeout=60)
            row={'command':command,'returncode':result.returncode,'stderr':result.stderr}
            records.append(row)
            if result.returncode:raise RuntimeError(result.stderr)
            row['result']=json.loads(result.stdout)
        if records[0]['result']!=saved['single']:raise ValueError('Frozen inference differs from original CPU evidence')
        if records[1]['result']['status']!='local_evidence_ready_for_test':raise ValueError('Release evidence is not ready')
        if records[3]['result']!=saved['batch']:raise ValueError('Frozen batch recovery differs from original CPU evidence')
    except BaseException as error:
        failure=type(error).__name__+': '+str(error)
        raise
    finally:
        atomic_json(output/'evidence.json',{'passed':failure is None,'failure':failure,'artifact':artifact,
                    'records':records,'new_remote_calls':0,'gpu_used':False,'llm_calls':0,
                    'scope':'Offline reuse of saved real CPU fixture; no new quality or production claim.'})
        print(output/'evidence.json')


if __name__=='__main__':main()
