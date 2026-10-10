"""Task-definition CLI, separate from training execution adapters."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .contracts import Sessions, validate_sample, validate_schema, validate_manifest


def interactive_action(message,session,args):
    """Reuse the durable CLI actions; never send unknown slash commands to LLM."""
    actions={'/readiness':'readiness','/prepare':'prepare','/run':'advance','/watch':'watch','/status':'agent-status',
             '/job':'status','/logs':'logs','/pause':'agent-pause','/resume':'agent-resume'}
    budget_value=None
    if message.split()[:1]==['/budget']:
        parts=message.split()
        if len(parts)!=2:
            print('用法：/budget GPU小时数，例如 /budget 32；仅设置初始上限，不修改已有预算。')
            return True
        budget_value=parts[1];actions[message]='budget'
    if message=='/help':
        print('/readiness 只读检查本地任务条件；/budget N 设置初始GPU小时上限；/prepare 检查训练计划；/run 推进有界执行；/watch 持续推进与观察；\n'
              '/status 查看本地控制记录；/job 实时查询远端作业；/logs 读取作业日志；\n'
              '/pause 暂停继续决策；/resume 恢复决策；/show 需求摘要；/contract 完整接口；/quit 保存退出。\n'
              '执行沿用当前会话的预算、研究轮数和时限。暂停或退出不取消已提交作业。')
        return True
    if message=='/show':return False
    if message not in actions:
        if message.startswith('/'):
            print('未知命令或命令参数；输入 /help 查看操作。此内容未发给模型。')
            return True
        return False
    action=actions[message]
    command=[action,'--session-id',session,'--sessions',args.sessions,'--config',args.config,
             '--run-store',args.run_store,'--campaign-store',args.campaign_store,'--registry',args.registry]
    if budget_value is not None:command+=['--gpu-hours',budget_value]
    if action in ('advance','watch','agent-status','agent-pause','agent-resume'):
        command+=['--steps',str(args.steps),'--watch-seconds',str(args.watch_seconds),'--poll-seconds',str(args.poll_seconds)]
        for flag,value in (('--research-rounds',args.research_rounds),('--campaign-id',args.campaign_id),
                           ('--candidate-id',args.candidate_id),('--candidate-module',args.candidate_module)):
            if value is not None:command+=[flag,str(value)]
        command+=['--candidate-store',args.candidate_store]
    if action in ('status','logs') and args.run_id:command+=['--run-id',args.run_id]
    if action=='prepare' and args.output:command+=['--output',args.output]
    if action=='agent-status':print('以下是本地控制记录；远端实时状态使用 /job。')
    try:
        main(command)
    except SystemExit:
        print('本次操作已结束；需求会话保留。输入 /show 查看。')
    except KeyboardInterrupt:
        print('\n已中断本地等待；远端作业及未结算记录保留，使用 /job 查询。')
    return True


def summary(result):
    labels={'clarifying':'需要补充关键信息','task_defined':'任务已明确；执行条件待补充','ready_for_harness':'接口检查通过','requirements_review':'需求变更待核对，原要求保留','requirements_not_dispatched':'需求请求未发送；原要求保留'}
    lines=['任务: '+result['task_id'], '会话: '+result['session_id'], '状态: '+labels.get(result['status'],result['status'])]
    if result.get('clarification_not_dispatched'):
        lines.append('请求在联网前被拒绝，需求文字已保存。解决准入条件后可再次 reply；无需解除不确定 API 请求。')
        lines.append('新需求尚未整理，Training 与新 harness 暂停执行。')
    elif result.get('pending_request'):
        lines.append('API 请求未完成保存；不会自动重发。')
        if result.get('pending_request_id'):
            lines.append('请求 ID: '+result['pending_request_id']+'；已保存响应: '+str(result.get('pending_response_count',0)))
            action='recover' if result.get('pending_response_count') else 'abandon-request'
            lines.append('若原进程已退出：training '+action+' --session-id '+result['session_id']+' --request-id '+result['pending_request_id'])
            if action=='abandon-request':lines.append('abandon-request 仅显式解除本地待处理状态；不取消服务端请求，结果及费用仍未知。')
        else:lines.append('旧版请求缺少恢复标识；原需求保留，请勿直接清除账本。')
    if result.get('unsettled_api_request_ids'):lines.append('存在已恢复/已解除请求的未知 API 结果或费用；未计为零。')
    if not result['versions']: return '\n'.join(lines+([] if result.get('pending_request') else ['需求描述已保存；尚未形成接口。']))
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
            'action_not_dispatched':'研究请求未发送；已暂停，解决准入条件后显式恢复','retry_authorized':'已允许重新提交未发送的研究请求',
            'controller_budget_exhausted':'本Campaign工具尝试预算已耗尽；保留作业与未完成意图','policy_stopped':'策略本次未选择动作','processing_result':'正在处理训练结果','ready':'训练计划已准备','new':'尚未推进'}
    lines=['状态: '+labels.get(result.get('status'),str(result.get('status')))]
    for key,label in [('task_id','任务'),('session_id','会话'),('campaign_id','Campaign'),('run_id','运行'),('version','能力版本'),('plan_path','计划文件'),('state_path','控制记录')]:
        if result.get(key): lines.append(label+': '+str(result[key]))
    if 'paused' in result:lines.append('继续决策: '+('已暂停（远端作业不会因此取消）' if result['paused'] else '未暂停'))
    intent=result.get('intent')
    if isinstance(intent,dict):
        action=intent.get('action') or {}
        attempts=intent.get('tool_attempts') or []
        lines.append('待处理动作: '+str(action.get('kind','未知'))+'；状态 '+str(intent.get('status','未知'))+'；已预留尝试 '+str(len(attempts)))
    if result.get('actual_gpu_hours') is not None: lines.append('实际 GPU 小时: '+str(result['actual_gpu_hours']))
    budget=result.get('controller_tool_budget')
    if isinstance(budget,dict):
        if budget.get('valid') is False:lines.append('控制预算记录无效: '+budget['error'])
        else:lines.append('本Campaign工具尝试: '+str(budget['admitted_attempts'])+' / '+str(budget['limit'])+'；剩余 '+str(budget['remaining_attempts']))
    plan=result.get('plan')
    plan=plan if isinstance(plan,dict) else {}
    if not result.get('plan_path') and plan.get('plan_path'):lines.append('计划文件: '+str(plan['plan_path']))
    blockers=result.get('blockers') or plan.get('blockers') or []
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
        diagnostic=verdict.get('error_summary')
        if diagnostic:
            totals=diagnostic['totals']
            lines.append('诊断匹配 (IoU='+str(diagnostic['iou_threshold'])+', score≥'+str(diagnostic['score_threshold'])+'): '
                         +'TP '+str(totals['true_positives'])+' / FP '+str(totals['false_positives'])+' / FN '+str(totals['false_negatives']))
            weak=diagnostic['weakest_annotated_categories'][:3]
            if weak:lines.append('低 AP 类别: '+', '.join(str(row['category_id'])+'='+str(round(row['box_AP'],3)) for row in weak))
    if result.get('log') is not None: lines.append(result['log'])
    if result.get('policy_stop'):
        stop=result['policy_stop']
        lines.append('策略停止原因: '+stop['decision']['rationale'])
        if stop.get('policy_evidence'):lines.append('策略执行证据: '+stop['policy_evidence'])
        if result.get('run_id'):lines.append('策略停止不取消远端作业；请按运行 ID 继续查询或取消。')
    if result.get('status')=='controller_budget_exhausted':
        lines.append('恢复不会刷新上限；保留此Campaign记录，不要通过新建Campaign绕过预算。')
        if result.get('run_id'):lines.append('下一步: training status/logs --run-id 查询原作业；确需终止时使用 cancel。')
    elif result.get('paused') and result.get('status')!='action_not_dispatched':
        lines.append('确认待处理动作后可 agent-resume；沿用同一会话、Campaign和存储配置。')
    return '\n'.join(lines)


def main(argv):
    parser=argparse.ArgumentParser(prog='vision-rsi training')
    parser.add_argument('action',choices=['start','reply','show','budget','accept','reject','recover','abandon-request','list','build','prepare','advance','watch','campaigns','audit','memory','readiness','release-status','research-init','research-step','research-status','research-watch','research-pause','research-resume','agent-status','agent-pause','agent-resume','status','logs','cancel','collect','resume','register','register-candidate','accept-candidate','candidate-acceptance-status','serving-evaluate','runs','diagnose','define','validate','export','run'])
    parser.add_argument('--task-id');parser.add_argument('--session-id')
    parser.add_argument('--goal');parser.add_argument('--requirements');parser.add_argument('--message')
    parser.add_argument('--gpu-hours',type=float,help='Explicit initial GPU-hour cap; never resets an existing execution budget')
    parser.add_argument('--contract');parser.add_argument('--sample');parser.add_argument('--result');parser.add_argument('--output')
    parser.add_argument('--manifest', help='JSONL samples for batch protocol validation')
    parser.add_argument('--interactive',action='store_true');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--sessions',default='runs/training-sessions')
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--json',action='store_true',help='Emit full structured records')
    parser.add_argument('--registry',default='runs/capabilities')
    parser.add_argument('--version')
    parser.add_argument('--bundle',help='Frozen candidate bundle to register as pending independent validation')
    parser.add_argument('--dataset',help='Explicit independent acceptance dataset')
    parser.add_argument('--development',action='append',help='Development execution JSON; repeat for each record')
    parser.add_argument('--request-id',help='Exact pending clarification request ID shown by training show')
    parser.add_argument('--wall-seconds-budget',type=float)
    parser.add_argument('--chunk-size',type=int,default=10)
    parser.add_argument('--run-id');parser.add_argument('--run-store',default='runs/training-runs')
    parser.add_argument('--campaign-store',default='runs/campaigns')
    parser.add_argument('--steps',type=int,default=3)
    parser.add_argument('--research-rounds',type=int,help='Bounded automatic method proposals after measured training failure (0..10; default 0)')
    parser.add_argument('--source-index',type=int,help='Zero-based original observation index from research memory')
    parser.add_argument('--context-sha256',help='Exact research memory snapshot hash for detail retrieval')
    parser.add_argument('--history-rows',type=int,help='Original snapshot length; permits lookup after later actions were appended')
    parser.add_argument('--campaign-id',help='Resume/query the exact persisted campaign and its frozen strategy/research settings')
    parser.add_argument('--watch-seconds',type=float,default=3600)
    parser.add_argument('--poll-seconds',type=float,default=15)
    parser.add_argument('--candidate-id');parser.add_argument('--candidate-module')
    parser.add_argument('--candidate-store',default='runs/research-candidates')
    parser.add_argument('--research-root',default='runs/task-research',help='Task-bound general research ledger root')
    parser.add_argument('--research-watch-turns',type=int,default=6,help='Maximum foreground general-research steps (1..1000)')
    parser.add_argument('--repository',default='.',help='Git source repository for general research; required explicitly outside the checkout')
    args=parser.parse_args(argv)
    if args.action in ('accept-candidate','candidate-acceptance-status'):
        if not args.session_id:parser.error('Candidate acceptance requires --session-id')
        if args.action=='accept-candidate' and (not args.version or not args.dataset or not args.development):
            parser.error('accept-candidate requires --version, --dataset and --development')
        import sqlite3
        from .capability import Capabilities
        from .task_acceptance import accept as accept_candidate, status as acceptance_status
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            registry=Capabilities(args.registry)
            try:
                if args.action=='candidate-acceptance-status':result=acceptance_status(registry,session['task_id'])
                else:
                    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
                    result=accept_candidate(registry,session,args.version,args.dataset,args.development,config['remote'])
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='register-candidate':
        if not args.session_id or not args.bundle:parser.error('register-candidate requires --session-id and --bundle')
        import sqlite3
        from .capability import Capabilities
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            registry=Capabilities(args.registry)
            try:result=registry.register_candidate(session,args.bundle)
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
        else:print('任务: '+result['task_id']+'\n版本: '+result['version']+'\n状态: 待独立验收；尚不能用于 test 推理')
        return
    if args.interactive and args.action not in ('start','show','reply','define'):
        parser.error('--interactive is supported for start/show/reply/define')
    if args.action=='release-status':
        import sqlite3
        from .release_status import inspect
        if not args.session_id:parser.error('release-status requires --session-id')
        try:result=inspect(args.session_id,args.sessions,args.registry)
        except (ValueError,OSError,KeyError,TypeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            print('任务发布证据: '+result['status'])
            for blocker in result['blockers']:print('- '+blocker)
            print('仅核查本地产物；未调用推理、远端或API，不代表整个Agent已上线。')
        return
    if args.action in ('research-init','research-step','research-status','research-watch','research-pause','research-resume'):
        from .task_research import prepare,advance,status,control
        import sqlite3
        if not args.session_id:parser.error('research requires --session-id')
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            if args.action=='research-init':result=prepare(session,args.research_root)
            elif args.action=='research-status':result=status(session,args.research_root)
            elif args.action in ('research-pause','research-resume'):
                result=control(session,args.action.removeprefix('research-'),args.research_root)
            elif args.action=='research-watch':
                from .research_watch import watch
                from .task_readiness import inspect
                def session_now():return Sessions(args.sessions,read_only=True).show(args.session_id)
                def next_step():
                    current=session_now()
                    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                    context=inspect(args.session_id,config,args.sessions,args.run_store,args.config)
                    from contextlib import redirect_stdout, nullcontext
                    import sys
                    with redirect_stdout(sys.stderr) if args.json else nullcontext():
                        return advance(current,config,args.research_root,1,args.repository,task_context=context,training_runs=args.run_store)
                result=watch(next_step,lambda:status(session_now(),args.research_root),
                             turns=args.research_watch_turns,duration=args.watch_seconds)
            else:
                from .task_readiness import inspect
                config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                context=inspect(args.session_id,config,args.sessions,args.run_store,args.config)
                from contextlib import redirect_stdout, nullcontext
                import sys
                with redirect_stdout(sys.stderr) if args.json else nullcontext():
                    result=advance(session,config,args.research_root,args.steps,args.repository,task_context=context,training_runs=args.run_store)
        except (ValueError,OSError,KeyError,TypeError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.action in ('research-status','research-pause','research-resume'):
            state=result['research_status']
            print('研究状态: '+state['state'])
            print('规划尝试: '+str(state['planning_attempts_used'])+' / '+str(state['planning_limit'])+'；剩余 '+str(state['planning_attempts_remaining']))
            print('本地调度记录；未验证进程存活或任务达标，不取消已在执行的调用。')
        elif args.action=='research-watch':
            print('研究监督已停止: '+result['watch']['stop_reason'])
            print('本轮完成步数: '+str(result['watch']['completed_steps']))
            print('报告: '+result['watch']['report_path'])
        else:
            print('任务研究: '+result['directory']+'\n观测页: '+result['dashboard'])
            print('固定接口版本: '+str(result['task_binding']['contract_version'])+'；未启动训练或采用候选。')
        return
    if args.action=='readiness':
        import sqlite3
        from .task_readiness import inspect
        if not args.session_id:parser.error('readiness requires --session-id')
        try:result=inspect(args.session_id,json.loads(Path(args.config).read_text(encoding='utf-8')),args.sessions,args.run_store,args.config)
        except (ValueError,OSError,KeyError,TypeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            print('只读本地就绪检查: '+result['status'])
            print('任务: '+result['task_id']+'；会话: '+result['session_id'])
            print('GPU小时预算: '+str(result['authorized_gpu_hours'])+'；本地剩余快照: '+str(result['remaining_gpu_hours_snapshot']))
            for blocker in result['blockers']:print('- '+blocker)
            for action in result['suggested_actions']:
                print('下一步: '+action['reason'])
                print('  python -m vision_rsi '+subprocess.list2cmdline(action['argv']))
            print('未调用API/SSH或启动训练；任务效果未检查。ready_for_prepare仅表示可继续准备计划。')
        return
    if args.action=='memory':
        from .research_memory import read_memory
        if not args.session_id or not args.campaign_id:parser.error('memory requires --session-id and --campaign-id')
        try:
            result=read_memory(args.session_id,args.campaign_id,args.campaign_store,args.source_index,args.context_sha256,args.history_rows)
        except (ValueError,OSError,KeyError,TypeError) as error:parser.exit(1,str(error)+'\n')
        if args.json or args.source_index is not None:print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            print('只读研究记忆；未查询远端。原始历史 '+str(result['history_rows'])+' 条，当前策略视图 '+str(result['view_rows'])+' 条。')
            print('上下文摘要: '+result['context_sha256'])
            view=result['view'];compacted=bool(view and view[0]['kind']=='memory_summary')
            indices=view[0]['observation']['source_indices'] if compacted else range(len(view))
            if compacted:print('省略历史 '+str(view[0]['observation']['omitted_rows'])+' 条；完整证据仍保留。')
            for index,item in list(zip(indices,view[1:] if compacted else view))[-16:]:
                print('['+str(index)+'] '+item['id']+' '+item['status'])
            print('取回原始诊断：增加 --source-index N --context-sha256 上述摘要 --history-rows '+str(result['history_rows']))
        return
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
                print('LLM提案尝试: '+str(result['llm_request_count'])+'，联网前拒绝 '+str(result['llm_not_dispatched_count'])+'，已准入或结果未知 '+str(result['llm_admitted_or_uncertain_count']))
                print('LLM tokens: 已知 '+str(result['known_llm_tokens'])+'，记录完整 '+str(result['llm_usage_complete']))
                print('已核验真实box AP: '+str(result['best_verified_real_box_AP']))
                print('策略决策轨迹核验: '+str(result['policy_trace']['verified']))
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
                    if args.session_id and runs.get(run_id)['session_id']!=args.session_id:
                        raise ValueError('Run belongs to another task session')
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
                if not args.offline:
                    from .executable_harness import build_executable
                    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
                    storage={'sessions':args.sessions,'runs':args.run_store,'campaigns':args.campaign_store,'registry':args.registry,'plans':'runs/training-plans'}
                    result=build_executable(store.show(session),result,config,storage,args.output or 'runs/harnesses')
            elif args.action=='reply':
                if not args.message: raise ValueError('--message required')
                result=clarify(session,args.message)
            elif args.action in ('recover','abandon-request'):
                result=store.resolve_request(session,args.request_id,abandon=args.action=='abandon-request')
            elif args.action in ('accept','reject'):
                if not args.version:raise ValueError('Specify --version with the exact pending requirements draft number')
                result=getattr(store,args.action)(session,int(args.version))
            elif args.action=='budget':
                if args.gpu_hours is None:raise ValueError('Specify --gpu-hours with the initial training budget')
                result=store.set_gpu_budget(session,args.gpu_hours)
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
                    message=input('描述需求或输入命令（/help 操作，/run 推进，/watch 观测，/quit 保存退出）：\n> ').strip()
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
                if interactive_action(message,session,args):
                    result=store.show(session)
                    continue
                if message=='/show': result=store.show(session)
                elif message: result=clarify(session,message)
        else:
            if not args.json and args.action in ('start','reply','show','budget','define','accept','reject','recover','abandon-request'):print(summary(result))
            else:print(execution_summary(result) if args.action in ('prepare','run') and not args.json else json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,RuntimeError,subprocess.SubprocessError) as error:
        if args.action in ('start','reply') and 'session' in locals():
            try:
                pending=store.show(session)
                if pending.get('pending_request'):print(summary(pending),file=sys.stderr)
            except (ValueError,OSError):pass
        parser.exit(1,str(error)+'\n')
