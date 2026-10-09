"""Task-definition CLI, separate from training execution adapters."""
import argparse
import hashlib
import json
from pathlib import Path

from .contracts import Sessions, validate_sample, validate_schema


def main(argv):
    parser=argparse.ArgumentParser(prog='vision-rsi training')
    parser.add_argument('action',choices=['start','reply','show','define','validate','export','run'])
    parser.add_argument('--task-id');parser.add_argument('--session-id')
    parser.add_argument('--goal');parser.add_argument('--requirements');parser.add_argument('--message')
    parser.add_argument('--contract');parser.add_argument('--sample');parser.add_argument('--result');parser.add_argument('--output')
    parser.add_argument('--interactive',action='store_true');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--config',default='config.local.json')
    args=parser.parse_args(argv)
    store=Sessions(args.sessions)
    def clarify(session,message=None):
        config=json.loads(Path(args.config).read_text(encoding='utf-8'))
        return store.clarify(session,config['llm'],message)
    try:
        if args.action=='start':
            goal=Path(args.requirements).read_text(encoding='utf-8') if args.requirements else args.goal
            if not goal and args.interactive: goal=input('请描述任务目标、输入输出与效果要求：\n> ')
            result=store.create(args.task_id,goal)
            session=result['session_id']
            print('session_id: '+session,flush=True)
            if args.contract: result=store.define(session,json.loads(Path(args.contract).read_text(encoding='utf-8')))
            elif not args.offline: result=clarify(session)
        else:
            session=args.session_id
            result=store.show(session)
            if args.action=='reply':
                if not args.message: raise ValueError('--message required')
                result=clarify(session,args.message)
            elif args.action=='define': result=store.define(session,json.loads(Path(args.contract).read_text(encoding='utf-8')))
            elif args.action in ('validate','export','run'):
                if not result['versions']: raise ValueError('No interface defined')
                latest=result['versions'][-1]
                if latest['issues']: raise ValueError('Interface incomplete: '+'; '.join(latest['issues']))
                contract=latest['contract']
                if args.action=='validate':
                    if args.sample: result=validate_sample(contract,json.loads(Path(args.sample).read_text(encoding='utf-8')))
                    elif args.result:
                        validate_schema(contract['output_schema'],json.loads(Path(args.result).read_text(encoding='utf-8')))
                        result={'valid':True}
                    else: result={'valid':True,'contract_version':latest['version']}
                elif args.action=='export':
                    if not args.output: raise ValueError('--output required')
                    result={'task_id':result['task_id'],'session_id':session,'contract_version':latest['version'],'contract':contract,'contract_sha256':hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
                    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                else:
                    result={'status':'blocked','session_id':session,'contract_version':latest['version'],'reason':'接口定义已完成；通用 harness 构建/训练适配器尚未接入。未执行训练或注册能力。'}
        if args.interactive:
            while True:
                print(json.dumps(result,ensure_ascii=False,indent=2))
                message=input('补充或纠正需求（/quit 保存退出，/show 查看）：\n> ').strip()
                if message=='/quit': break
                if message=='/show': result=store.show(session)
                elif message: result=clarify(session,message)
        else: print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
        parser.exit(1,str(error)+'\n')
