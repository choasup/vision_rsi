"""Opt-in real CPU video decode-to-candidate fixture; no model quality claim."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_rsi.candidates import Candidates
from vision_rsi.candidate_bundle import build,run
from vision_rsi.runner import atomic_json
import vision_rsi.remote as transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-remote',action='store_true');parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args()
    if not args.live_remote:parser.error('--live-remote required; one tiny CPU clip generation, one decode, one candidate execution')
    repo=Path(__file__).resolve().parents[1];remote=json.loads(Path(args.config).read_text())['remote']
    folder=repo/'runs/bundle-video-live'/uuid.uuid4().hex;folder.mkdir(parents=True);print(str(folder),flush=True)
    atomic_json(folder/'preregistered.json',{'scope':__doc__,'expected_generation_calls':1,'expected_decode_calls':1,
        'expected_candidate_calls':1,'llm_calls':0,'gpu_allowed':False,'criteria':['frame metadata read by candidate','exact repeat uses caches']})
    decode_original=transport.decode_video;check_original=transport.check_candidate;counts={'decode':0,'candidate':0}
    def decode(*values):counts['decode']+=1;return decode_original(*values)
    def check(*values):counts['candidate']+=1;return check_original(*values)
    transport.decode_video=decode;transport.check_candidate=check
    store=None;passed=False;failure=None;execution=None
    try:
        program="import subprocess,base64,tempfile,pathlib; t=tempfile.TemporaryDirectory(); p=pathlib.Path(t.name)/'fixture.mkv'; subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=16x16:r=2:d=1','-c:v','ffv1',str(p)],capture_output=True,timeout=20,check=True); print(base64.b64encode(p.read_bytes()).decode()); t.cleanup()"
        command=shlex.quote(remote.get('python','python3'))+' -c '+shlex.quote(program)
        clip=subprocess.run(transport.ssh_argv(remote)+[command],capture_output=True,text=True,timeout=30,check=True)
        raw=base64.b64decode(clip.stdout.strip(),validate=True);assert 0<len(raw)<512*1024
        (folder/'fixture.mkv').write_bytes(raw)
        contract=json.loads((repo/'examples/interface-contract.json').read_text())
        contract['goal']='Developer video frame transport fixture; no learned model'
        contract['inputs']={'clip':contract['inputs']['clip']}
        contract['inputs']['clip']['processing']['decoder']={'protocol':'source_time_grid_v2','fps':2,'max_frames':4,
            'max_width':16,'max_height':16,'max_duration_seconds':2,'audio':'ignore'}
        sample={'sample_id':'clip','inputs':{'clip':{'type':'video','uri':'fixture.mkv'}}};contract['example_input']=sample
        atomic_json(folder/'contract.json',contract)
        proposal={'hypothesis':'Check actual decoded frames reach candidate','expected_improvement':'No visual quality claim',
            'evaluation_plan':'Read real source frame metadata, then repeat without transport',
            'edits':[{'path':'vision_rsi/adapter_video_probe.py','base_sha256':None,
                'content':'import base64\ndef predict(sample,media,video_frames):\n    frames=video_frames["clip"]["frames"]\n    raw=base64.b64decode(frames[0]["content_base64"])\n    assert raw.startswith(b"P6\\n16 16\\n255\\n")\n    return {"defects":[{"label":"frame-read","start_seconds":frames[0]["seconds"]}]}\n'}]}
        store=Candidates(folder/'candidates',repo);candidate=store.create(proposal,{'fixture':True})
        bundle=build(store,candidate['candidate_id'],'vision_rsi.adapter_video_probe','predict',folder/'contract.json',folder/'bundles',True,True)
        execution=run(bundle['path'],[sample],remote,folder/'executions',bundle['bundle_id'],folder)
        assert execution['outputs'][0]['defects'][0]['label']=='frame-read'
        assert run(bundle['path'],[sample],remote,folder/'executions',bundle['bundle_id'],folder)==execution
        assert counts=={'decode':1,'candidate':1}
        passed=True
    except Exception as error:failure=type(error).__name__+': '+str(error)[:500]
    finally:
        transport.decode_video=decode_original;transport.check_candidate=check_original
        if store is not None:store.close()
    evidence={'passed':passed,'failure':failure,'counts':counts,'execution_path':execution.get('execution_path') if execution else None,
              'quality_verified':False,'gpu_used':False,'llm_called':False,'scope':__doc__}
    atomic_json(folder/'evidence.json',evidence);print(json.dumps(evidence,indent=2));return int(not passed)


if __name__=='__main__':raise SystemExit(main())
