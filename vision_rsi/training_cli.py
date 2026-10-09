"""Task-definition CLI, separate from training execution adapters."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from .contracts import Sessions, validate_sample, validate_schema, validate_manifest


def summary(result):
    labels={'clarifying':'需要补充关键信息','task_defined':'任务已明确；执行条件待补充','ready_for_harness':'接口检查通过'}
    lines=['任务: '+result['task_id'], '会话: '+result['session_id'], '状态: '+labels.get(result['status'],result['status'])]
    if not result['versions']: return '\n'.join(lines+['请描述你要完成的任务。'])
    latest=result['versions'][-1];contract=latest['contract']
    lines+=['已理解: '+str(contract.get('goal','正在整理你的需求'))]
    inputs=contract.get('inputs') or {}
    if inputs: lines.append('输入: '+', '.join(name+' ('+str(field.get('type'))+')' for name,field in inputs.items() if isinstance(field,dict)))
    props=(contract.get('output_schema') or {}).get('properties') or {}
    if props: lines.append('输出: '+', '.join(props))
    acceptance=contract.get('acceptance') or {}
    if acceptance.get('threshold') is not None:
        lines.append('效果目标: '+str(acceptance.get('metric'))+' '+('≥' if acceptance.get('direction')=='maximize' else '≤')+' '+str(acceptance['threshold']))
    if result['status']=='task_defined':
        lines.append('需求已保存，无需重复说明。Agent 会选择模型和训练方法。')
        if not contract.get('budget'): lines.append('执行前待补充: 最多允许多少 GPU 小时（8 卡运行 1 小时 = 8 GPU 小时）。')
        else: lines.append('执行前会核查剩余问题；/contract 可查看完整定义。')
    elif latest['issues']:
        questions=contract.get('open_questions') or []
        if questions: lines+=['需要你补充:']+['- '+str(q) for q in questions[:2]]
        else: lines.append('接口整理尚有问题，已保留你的描述；无需填写内部 schema 字段。')
    else: lines.append('任务接口已保存。可用 training prepare 检查执行配置。')
    return '\n'.join(lines)


def execution_summary(result):
    labels={'blocked':'执行条件待补充','ready_to_submit':'训练计划已准备','submitted':'远端作业已提交',
            'submission_uncertain':'提交响应不确定，请查询原作业','completed':'远端进程已结束；需检查评测结果',
            'running':'远端作业运行中','cancelled':'已取消','timed_out':'已超时','failed':'执行失败'}
    lines=['状态: '+labels.get(result.get('status'),str(result.get('status')))]
    for key,label in [('task_id','任务'),('session_id','会话'),('run_id','运行'),('plan_path','计划文件')]:
        if result.get(key): lines.append(label+': '+str(result[key]))
    if result.get('actual_gpu_hours') is not None: lines.append('实际 GPU 小时: '+str(result['actual_gpu_hours']))
    blockers=result.get('blockers') or []
    immediate=[x for x in blockers if not x.startswith('待澄清:')]
    if immediate:
        lines.append('需求已保存；执行前需要解决:')
        lines.extend('- '+str(x) for x in immediate[:3])
        if len(blockers)>len(immediate[:3]): lines.append('其他检查项已保存在计划文件中。')
    if result.get('log') is not None: lines.append(result['log'])
    return '\n'.join(lines)


def main(argv):
    parser=argparse.ArgumentParser(prog='vision-rsi training')
    parser.add_argument('action',choices=['start','reply','show','list','build','prepare','status','logs','cancel','runs','diagnose','define','validate','export','run'])
    parser.add_argument('--task-id');parser.add_argument('--session-id')
    parser.add_argument('--goal');parser.add_argument('--requirements');parser.add_argument('--message')
    parser.add_argument('--contract');parser.add_argument('--sample');parser.add_argument('--result');parser.add_argument('--output')
    parser.add_argument('--manifest', help='JSONL samples for batch protocol validation')
    parser.add_argument('--interactive',action='store_true');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--json',action='store_true',help='Emit full structured records')
    parser.add_argument('--run-id');parser.add_argument('--run-store',default='runs/training-runs')
    args=parser.parse_args(argv)
    if args.interactive and args.action not in ('start','show','reply','define'):
        parser.error('--interactive is supported for start/show/reply/define')
    store=Sessions(args.sessions)
    def clarify(session,message=None):
        config=json.loads(Path(args.config).read_text(encoding='utf-8'))
        return store.clarify(session,config['llm'],message)
    try:
        if args.action in ('status','logs','cancel','runs'):
            from .training_runs import TrainingRuns,observe
            runs=TrainingRuns(args.run_store)
            try:
                if args.action=='runs': result=runs.list(args.session_id)
                else:
                    run_id=args.run_id
                    if not run_id:
                        previous=runs.list(args.session_id)
                        if not previous: raise ValueError('No Training runs for this session')
                        run_id=previous[-1]['run_id']
                    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                    result=observe(run_id,config['remote'],runs,args.action)
            finally: runs.close()
            print(json.dumps(result,ensure_ascii=False,indent=2) if args.json or args.action=='runs' else execution_summary(result));return
        if args.action=='list':
            print(json.dumps(store.list(),ensure_ascii=False,indent=2))
            return
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
            if args.action=='diagnose':
                from .remote import detector_request
                from .runner import atomic_json, revision
                config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                result={'session_id':session,'task_id':result['task_id'],'contract_version':len(result['versions']),'git_revision':revision(),'adapter_source_sha256':hashlib.sha256(Path(__file__).with_name('detector.py').read_bytes()).hexdigest(),'dataset':detector_request(config['remote'],'dataset-check'),'detector':detector_request(config['remote'],'smoke')}
                destination=Path(args.sessions)/('diagnosis-'+session+'.json')
                atomic_json(destination,result)
                result['report']=str(destination.resolve())
            elif args.action=='run':
                from .training_plan import prepare
                from .training_runs import TrainingRuns,submit
                config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                plan=prepare(result,config,args.output or 'runs/training-plans')
                runs=TrainingRuns(args.run_store)
                try: result=submit(plan,config.get('remote',{}),runs)
                finally: runs.close()
            elif args.action=='prepare':
                from .training_plan import prepare
                config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                result=prepare(result,config,args.output or 'runs/training-plans')
            elif args.action=='build':
                from .harness import build
                result=build(result,args.output or 'runs/harnesses')
            elif args.action=='reply':
                if not args.message: raise ValueError('--message required')
                result=clarify(session,args.message)
            elif args.action=='define': result=store.define(session,json.loads(Path(args.contract).read_text(encoding='utf-8')))
            elif args.action in ('validate','export'):
                if not result['versions']: raise ValueError('No interface defined')
                latest=result['versions'][-1]
                if latest['issues']: raise ValueError('Interface incomplete: '+'; '.join(latest['issues']))
                contract=latest['contract']
                if args.action=='validate':
                    if sum(bool(x) for x in (args.sample,args.result,args.manifest)) > 1:
                        raise ValueError('Choose only one: --sample, --manifest, --result')
                    if args.manifest: result=validate_manifest(contract,args.manifest)
                    elif args.sample: result=validate_sample(contract,json.loads(Path(args.sample).read_text(encoding='utf-8')))
                    elif args.result:
                        validate_schema(contract['output_schema'],json.loads(Path(args.result).read_text(encoding='utf-8')))
                        result={'valid':True}
                    else: result={'valid':True,'contract_version':latest['version']}
                elif args.action=='export':
                    if not args.output: raise ValueError('--output required')
                    result={'task_id':result['task_id'],'session_id':session,'contract_version':latest['version'],'contract':contract,'contract_sha256':hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
                    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if args.interactive:
            while True:
                print(summary(result))
                try:
                    message=input('补充需求（/quit 退出，/show 摘要，/contract 完整接口）：\n> ').strip()
                except (EOFError, KeyboardInterrupt):
                    print('\n会话已保存。session_id: '+session)
                    break
                if message=='/quit': break
                if message=='/contract':
                    current=store.show(session)
                    print(json.dumps(current['versions'][-1]['contract'] if current['versions'] else {},ensure_ascii=False,indent=2))
                    continue
                if message=='/show': result=store.show(session)
                elif message: result=clarify(session,message)
        else:
            print(execution_summary(result) if args.action in ('prepare','run') and not args.json else json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
