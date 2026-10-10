"""Local independent-process budget probe; fixture config cannot submit training."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.contracts import Sessions
from vision_rsi.runner import atomic_json


def main():
    repo=Path(__file__).resolve().parents[1]
    folder=repo/'runs'/('cb-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    contract=json.loads((repo/'examples/interface-contract.json').read_text(encoding='utf-8'))
    contract['budget']=None
    store=Sessions(folder/'sessions');session=store.create('budget-fixture','Synthetic interface only; no training authorization')
    session=store.define(session['session_id'],contract)
    atomic_json(folder/'config.json',{'remote':{'ssh_host':'fixture-not-contacted','workspace':'/fixture'},'llm':{},'controller':{'tool_attempt_limit':1}})
    base=[sys.executable,'-X','utf8','-m','vision_rsi','training']
    scope=['--session-id',session['session_id'],'--config',str(folder/'config.json'),'--sessions',str(folder/'sessions'),'--run-store',str(folder/'runs'),'--campaign-store',str(folder/'campaigns'),'--json']
    def call(action,*extra):
        result=subprocess.run(base+[action]+scope+list(extra),cwd=repo,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    first=call('advance','--steps','10');assert first['status']=='blocked'
    second=call('advance','--steps','10');assert second['status']=='controller_budget_exhausted'
    before=Path(second['state_path']).read_bytes()
    third=call('advance');assert Path(second['state_path']).read_bytes()==before
    watched=call('watch','--watch-seconds','5','--poll-seconds','5')
    assert watched['watch']['stop_reason']=='controller_budget_exhausted'
    assert all(row['controller_tool_budget']['admitted_attempts']==1 for row in (first,second,third,watched))
    assert all(len(row['history'])==1 and row['history'][0]['action']['kind']=='prepare' for row in (first,second,third,watched))
    assert not any(row.get('run_id') for row in (first,second,third,watched))
    evidence={'fixture':True,'directory':str(folder),'session_id':session['session_id'],'campaign_id':second['campaign_id'],
              'independent_cli_processes':4,'tool_attempt_limit':1,'admitted_attempts_after_each_process':[1,1,1,1],
              'statuses':[row['status'] for row in (first,second,third,watched)],'watch_stop_reason':watched['watch']['stop_reason'],
              'repeated_advance_state_unchanged':True,'run_created':False,'gpu_used':False,'llm_called':False,
              'scope':'Per-campaign tool attempts only, not whole-session resources or policy call cost.'}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
