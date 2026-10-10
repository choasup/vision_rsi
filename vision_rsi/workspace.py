"""Create a non-secret local configuration without contacting services."""
import argparse
import json
from pathlib import Path


def initialize(directory):
    root=Path(directory).resolve()
    config={'mode':'mock','seed':42,'budget_gpu_hours':0,'max_experiments':0,
            'detector':'UNSELECTED','pretrained_weights':'UNCONFIGURED',
            'dataset':'UNCONFIGURED',
            'research':{'allow_candidate_writes':False,'allow_candidate_checks':False,'max_planning_requests':6},
            'llm':{'provider':'openai-compatible','base_url':'https://api.deepseek.com',
                   'model':'deepseek-flash','api_key_env':'DEEPSEEK_API_KEY'},
            'remote':{'ssh_host':'','workspace':'','coco_root':'','ssh_port':22,'python':'python3'}}
    root.mkdir(parents=True,exist_ok=True)
    path=root/'config.local.json'
    # Exclusive creation: concurrent initialization cannot replace user configuration.
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(config,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    return {'directory':str(root),'config':str(path),'created':True,
            'api_called':False,'ssh_called':False,'gpu_training_authorized':False,
            'api_key_saved':False,'configuration_ready':False,
            'next_steps':['Set DEEPSEEK_API_KEY in the local environment; never paste it into config.',
                          'Edit remote SSH/workspace/data fields for actual training; template fields are empty.',
                          'Run training start with --config "'+str(path)+'" --sessions "'+str(root/'runs/training-sessions')+'" --task-id TASK --goal "Describe requirements" --interactive.',
                          'Provide an explicit task GPU-hour budget before real training.',
                          'General candidate code research needs --repository pointing to a Git source checkout; the installed wheel alone is not a checkout.']}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='vision-rsi workspace-init',description=__doc__)
    parser.add_argument('--directory',default='.',help='Workspace directory; never overwrites config.local.json')
    args=parser.parse_args(argv)
    try:result=initialize(args.directory)
    except (OSError,ValueError) as error:parser.exit(1,type(error).__name__+': '+str(error)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
