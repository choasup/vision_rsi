"""Task-definition CLI, separate from training execution adapters."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .contracts import Sessions, validate_sample, validate_schema, validate_manifest


def summary(result):
    labels={'clarifying':'需要补充关键信息','task_defined':'任务已明确；执行条件待补充','ready_for_harness':'接口检查通过','requirements_review':'需求变更待核对，原要求保留'}
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
    if latest.get('review_required'):
        lines.append('模型提出以下变更，尚未生效:')
        for change in latest['review_required']:
            if change['path'] in ('inputs','output_schema'):lines.append('- '+change['path']+': 接口发生变化（/contract 查看草案）')
            else:lines.append('- '+change['path']+': '+str(change['before'])[:160]+' → '+str(change['after'])[:160])
        lines.append('草案版本: '+str(latest['version'])+'；/accept 接受，/reject 保留原要求；也可继续自然语言修正。')
    elif result['status']=='task_defined':
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
            'running':'远端作业运行中','cancelled':'已取消','timed_out':'已超时','failed':'执行失败',
            'waiting':'已提交；等待远端作业','needs_research':'已分析结果；需要下一轮研究',
            'awaiting_serving_validation':'训练证据通过；需要推理后端验收','action_uncertain':'动作结果不确定；保留原作业与预留',
            'policy_stopped':'策略本次未选择动作','processing_result':'正在处理训练结果','ready':'训练计划已准备','new':'尚未推进'}
    lines=['状态: '+labels.get(result.get('status'),str(result.get('status')))]
    for key,label in [('task_id','任务'),('session_id','会话'),('run_id','运行'),('version','能力版本'),('plan_path','计划文件')]:
        if result.get(key): lines.append(label+': '+str(result[key]))
    if result.get('actual_gpu_hours') is not None: lines.append('实际 GPU 小时: '+str(result['actual_gpu_hours']))
    blockers=result.get('blockers') or []
    immediate=[x for x in blockers if not x.startswith('待澄清:')]
    if immediate:
        lines.append('需求已保存；执行前需要解决:')
        lines.extend('- '+str(x) for x in immediate[:3])
        if len(blockers)>len(immediate[:3]): lines.append('其他检查项已保存在计划文件中。')
    verdict=result.get('details',{}).get('acceptance_review')
    if verdict:
        lines.append('效果验收: '+str(verdict['status']))
        if 'box_AP' in verdict: lines.append('box AP: '+str(verdict['box_AP'])+' / 目标: '+str(verdict['threshold']))
        if verdict.get('reason'): lines.append(verdict['reason'])
        lines.extend('- '+reason for reason in verdict.get('reasons',[]))
    if result.get('log') is not None: lines.append(result['log'])
    return '\n'.join(lines)


def main(argv):
    parser=argparse.ArgumentParser(prog='vision-rsi training')
    parser.add_argument('action',choices=['start','reply','show','accept','reject','list','build','prepare','advance','watch','campaigns','audit','agent-status','agent-pause','agent-resume','status','logs','cancel','collect','resume','register','serving-evaluate','runs','diagnose','define','validate','export','run'])
    parser.add_argument('--task-id');parser.add_argument('--session-id')
    parser.add_argument('--goal');parser.add_argument('--requirements');parser.add_argument('--message')
    parser.add_argument('--contract');parser.add_argument('--sample');parser.add_argument('--result');parser.add_argument('--output')
    parser.add_argument('--manifest', help='JSONL samples for batch protocol validation')
    parser.add_argument('--interactive',action='store_true');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--json',action='store_true',help='Emit full structured records')
    parser.add_argument('--registry',default='runs/capabilities')
    parser.add_argument('--version')
    parser.add_argument('--wall-seconds-budget',type=float)
    parser.add_argument('--chunk-size',type=int,default=10)
    parser.add_argument('--run-id');parser.add_argument('--run-store',default='runs/training-runs')
    parser.add_argument('--campaign-store',default='runs/campaigns')
    parser.add_argument('--steps',type=int,default=3)
    parser.add_argument('--research-rounds',type=int,help='Bounded automatic method proposals after measured training failure (0..10; default 0)')
    parser.add_argument('--campaign-id',help='Resume/query the exact persisted campaign and its frozen strategy/research settings')
    parser.add_argument('--watch-seconds',type=float,default=3600)
    parser.add_argument('--poll-seconds',type=float,default=15)
    parser.add_argument('--candidate-id');parser.add_argument('--candidate-module')
    parser.add_argument('--candidate-store',default='runs/research-candidates')
    args=parser.parse_args(argv)
    if args.interactive and args.action not in ('start','show','reply','define'):
        parser.error('--interactive is supported for start/show/reply/define')
    store=Sessions(args.sessions)
    def clarify(session,message=None):
        config=json.loads(Path(args.config).read_text(encoding='utf-8'))
        return store.clarify(session,config['llm'],message)
    try:
        if args.action=='audit':
            from .campaign_audit import audit
            if not args.session_id or not args.campaign_id:parser.error('audit requires --session-id and --campaign-id')
            result=audit(args.session_id,args.campaign_id,args.campaign_store,args.run_store)
            if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
            else:
                print('Campaign: '+result['campaign_id'])
                print('GPU小时: 已结算 '+str(result['settled_gpu_hours'])+'，仍预留 '+str(result['held_gpu_hours']))
                print('LLM tokens: 已知 '+str(result['known_llm_tokens'])+'，记录完整 '+str(result['llm_usage_complete']))
                print('已核验真实box AP: '+str(result['best_verified_real_box_AP']))
                for item in result['missing_evidence']:print('- '+item)
                print('单流程证据审计；未证明RSI提升，未采用候选。')
            return
        if args.action=='campaigns':
            from .campaign import list_campaigns
            if not args.session_id:parser.error('campaigns requires --session-id')
            store.show(args.session_id)
            records=list_campaigns(args.session_id,args.campaign_store)
            if args.json:print(json.dumps(records,ensure_ascii=False,indent=2))
            else:
                for record in records:
                    print(record['campaign_id']+' | '+record['status']+(' [paused]' if record['paused'] else '')+' | rounds='+str(record['research_rounds'])+' | run='+str(record['run_id']))
                print('以上为本地保存的最近状态；实时核查作业请用training status --run-id。')
            return
        if args.action in ('advance','watch','agent-status','agent-pause','agent-resume'):
            from .campaign import advance
            if bool(args.candidate_id)!=bool(args.candidate_module):parser.error('Experimental policy requires both --candidate-id and --candidate-module')
            policy={'candidate_id':args.candidate_id,'module':args.candidate_module,'store':str(Path(args.candidate_store).resolve())} if args.candidate_id else None
            config=json.loads(Path(args.config).read_text(encoding='utf-8'))
            if args.action=='watch':
                from .watch import watch
                def progress(event):
                    print(json.dumps(event,ensure_ascii=False),flush=True,file=sys.stderr if args.json else sys.stdout)
                result=watch(lambda:store.show(args.session_id),lambda:json.loads(Path(args.config).read_text(encoding='utf-8')),
                             args.campaign_store,args.run_store,args.steps,policy,args.research_rounds,args.campaign_id,
                             args.watch_seconds,args.poll_seconds,progress)
            else:
                result=advance(store.show(args.session_id),config,args.campaign_store,args.run_store,args.steps,policy,
                               {'agent-status':'show','agent-pause':'pause','agent-resume':'resume'}.get(args.action),args.research_rounds,args.campaign_id)
            if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
            else:
                print(execution_summary(result))
                if result.get('state_path'):print('控制记录: '+result['state_path'])
                if result.get('campaign_id'):print('Campaign: '+result['campaign_id'])
                if result.get('paused'):print('控制器已暂停；已提交远端作业仍按原预算运行，取消作业请用training cancel。')
                if result.get('analysis'):print('结果分析: '+json.dumps(result['analysis'],ensure_ascii=False))
                if policy:print('使用实验候选策略；不代表策略已通过效率验收或被采用。')
                if result.get('watch'):print('持续观察结束: '+result['watch']['stop_reason']+'；未取消远端作业。')
            if result.get('watch',{}).get('stop_reason') in ('needs_attention','state_unavailable'):
                parser.exit(1,result['watch'].get('last_observation_error','Controller needs attention')+'\n')
            return
        if args.action=='serving-evaluate':
            if not args.task_id or not args.version or args.wall_seconds_budget is None:
                parser.error('serving-evaluate requires --task-id, --version and --wall-seconds-budget')
            from .capability import Capabilities
            registry=Capabilities(args.registry)
            try:result=registry.evaluate_serving(args.task_id,args.version,args.wall_seconds_budget,args.chunk_size)
            finally:registry.close()
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if args.action in ('status','logs','cancel','collect','resume','register','runs'):
            from .training_runs import TrainingRuns,observe,collect,resume
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
                    if args.action=='collect': result=collect(run_id,config['remote'],runs)
                    elif args.action=='resume': result=resume(run_id,config['remote'],runs)
                    elif args.action=='register':
                        from .capability import Capabilities
                        record=collect(run_id,config['remote'],runs)
                        registry=Capabilities(args.registry)
                        try: result=registry.register_training(record,args.sample)
                        finally: registry.close()
                    else: result=observe(run_id,config['remote'],runs,args.action)
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
            elif args.action in ('accept','reject'):
                if not args.version:raise ValueError('Specify --version with the exact pending requirements draft number')
                result=getattr(store,args.action)(session,int(args.version))
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
                    message=input('补充需求（/quit 退出，/show 摘要，/contract 接口，/accept 接受变更，/reject 拒绝）：\n> ').strip()
                except (EOFError, KeyboardInterrupt):
                    print('\n会话已保存。session_id: '+session)
                    break
                if message=='/quit': break
                if message=='/contract':
                    current=store.show(session)
                    latest=current['versions'][-1] if current['versions'] else {}
                    contract={'active_contract':latest['contract'],'proposed_contract':latest['proposed_contract'],'draft_version':latest['version']} if latest.get('review_required') else latest.get('contract',{})
                    print(json.dumps(contract,ensure_ascii=False,indent=2))
                    continue
                if message in ('/accept','/reject'):
                    current=store.show(session)
                    if not current['versions']:print('当前没有需求草案。');continue
                    result=getattr(store,message[1:])(session,current['versions'][-1]['version'])
                    continue
                if message=='/show': result=store.show(session)
                elif message: result=clarify(session,message)
        else:
            if not args.json and args.action in ('start','reply','show','define','accept','reject'):print(summary(result))
            else:print(execution_summary(result) if args.action in ('prepare','run') and not args.json else json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
