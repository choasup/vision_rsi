"""Task-definition CLI, separate from training execution adapters."""
import argparse
import hashlib
import json
import subprocess
import sys
import shlex
from pathlib import Path

from .contracts import Sessions, GPU_BUDGET_QUESTION, task_questions, validate_sample, validate_schema, validate_manifest


def interactive_action(message,session,args):
    """Reuse the durable CLI actions; never send unknown slash commands to LLM."""
    actions={'/readiness':'readiness','/prepare':'prepare','/run':'advance','/watch':'watch','/status':'agent-status',
             '/job':'status','/logs':'logs','/pause':'agent-pause','/resume':'agent-resume',
             '/research':'research-step','/research-watch':'research-watch','/research-status':'research-status',
             '/research-pause':'research-pause','/research-resume':'research-resume',
             '/select':'select-candidate','/release':'release-status','/harness':'harness-plan',
             '/harness-next':'harness-advance','/harness-generate':'harness-advance',
             '/harness-check':'harness-advance','/harness-status':'harness-status'}
    extra=['--autonomous'] if message=='/harness-next' else []
    if message=='/harness-generate':extra=['--generate-backend']
    if message=='/harness-check':extra=['--check-backend']
    head=message.split()[:1]
    if head in (['/deliver'],['/delivery']):
        try:
            # Preserve Windows backslashes, including paths quoted for spaces.
            parts=[value[1:-1] if value.startswith('"') and value.endswith('"') else value
                   for value in shlex.split(message,posix=False)]
        except ValueError:
            print('路径引号未闭合；本次操作未执行。');return True
        if parts[0]=='/deliver' and len(parts)==3:
            actions[message]='deliver-candidate'
            extra=['--select-development','--dataset',parts[1],'--max-latency-seconds',parts[2]]
        elif parts[0]=='/delivery' and len(parts)==2:
            actions[message]='delivery-status';extra=['--version',parts[1]]
        else:
            print('用法：/deliver "独立验收集路径" 最大延迟秒数；/delivery 原候选版本。交付前先 /research-pause。')
            return True
    budget_value=None
    if message.split()[:1]==['/budget']:
        parts=message.split()
        if len(parts)!=2:
            print('用法：/budget GPU小时数，例如 /budget 32；仅设置初始上限，不修改已有预算。')
            return True
        budget_value=parts[1];actions[message]='budget'
    if message=='/help':
        print('开始吧 / 继续：自动调用 API 生成候选、执行已配置的隔离检查，明确失败时修复一次；查看进度：读取保存的步骤。\n'
              '生成后端：调用 API 编写隔离候选；测试后端：在已配置远端执行隔离协议测试。\n'
              '/harness 生成任务执行规格（不训练）；/readiness 只读检查本地任务条件；/budget N 设置初始GPU小时上限；/prepare 检查训练计划；/run 推进有界执行；/watch 持续推进与观察；\n'
              '/status 查看本地控制记录；/job 实时查询远端作业；/logs 读取作业日志；\n'
              '/pause 暂停继续决策；/resume 恢复决策；/show 需求摘要；/contract 完整接口；/quit 保存退出。\n'
              '/research 推进一步通用研究；/research-watch 有界持续研究；/research-status 查看研究记录；\n'
              '/research-pause 暂停通用研究；/research-resume 恢复通用研究；/select 冻结开发选型；\n'
              '/deliver "验收集路径" 延迟秒数 自动选型并交付；/delivery 原候选版本 查看交付记录；/release 只读发布证据。\n'
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
    command+=extra
    if action in ('harness-advance','harness-status'):
        command+=['--repository',args.repository,'--harness-root',args.harness_root]
    if action.startswith('research-') or action in ('select-candidate','deliver-candidate'):
        command+=['--research-root',args.research_root]
    if action in ('research-step','research-watch'):
        command+=['--repository',args.repository,'--steps',str(args.steps),
                  '--research-watch-turns',str(args.research_watch_turns),'--watch-seconds',str(args.watch_seconds)]
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


def conversation_summary(result):
    """Show the next decision, keeping the full contract available on demand."""
    if (result.get('pending_request') or result.get('clarification_not_dispatched')
            or result.get('unsettled_api_request_ids')):
        return summary(result)
    if not result['versions']:
        return '需求已保存。请继续描述你想完成的任务，例如：输入一张图片，判断是猫还是狗。'
    latest=result['versions'][-1]
    reviewing=bool(latest.get('review_required'))
    contract=latest.get('proposed_contract',latest['contract']) if reviewing else latest['contract']
    lines=['我理解你想做：'+str(contract.get('goal','正在整理你的需求'))]
    from .task_adapters import training_adapter
    supported=training_adapter(contract)['implementation_supported']
    task_complete=not task_questions(contract) and (not latest.get('issues') or result.get('status')=='task_defined')
    if 'data_source' in contract:
        from .contracts import interface_issues
        task_complete=not task_questions(contract) and not interface_issues(contract)
    last_message=next((turn['content'] for turn in reversed(result.get('turns',[]))
                       if turn.get('role')=='user'),'')
    requested_advice=any(word in last_message for word in ('建议','不知道','不确定'))
    if latest.get('assistant_message') and (reviewing or not task_complete or supported or requested_advice):
        lines.append('建议与说明：'+latest['assistant_message'])
    else:
        if (requested_advice
                and GPU_BUDGET_QUESTION in (contract.get('open_questions') or [])):
            lines.append('建议先完成需求定义，不启动训练，也不用现在猜 GPU 预算。'
                         '准备好数据和训练设备后，先估算一次小规模试验的用量，再由你确认上限。'
                         'GPU 小时 = 使用的 GPU 卡数 × 运行小时数。')
    if reviewing:
        labels={'goal':'任务目标','inputs':'输入内容','output_schema':'输出内容',
                'acceptance':'验收要求','acceptance.metric':'验收指标',
                'acceptance.threshold':'效果目标','acceptance.direction':'指标方向',
                'acceptance.evaluation_protocol':'评测方法','budget':'资源预算'}
        for change in latest['review_required']:
            path=change['path']
            if path=='goal':continue
            label=labels.get(path,path)
            if path in ('inputs','output_schema'):
                lines.append(label+'有调整，可输入 /contract 查看完整草案。')
            else:
                lines.append(label+'：'+str(change['before'])+' → '+str(change['after']))
        lines.append('以上是待确认的新需求，尚未生效。是否正确？')
        lines.append('输入“是”确认，输入“否”保留原需求，或直接说要修改什么。')
        return '\n'.join(lines)
    # Keep authorization gaps in the ledger and execution checks, but do not
    # make a novice choose GPU hours before defining the task.
    questions=task_questions(contract)
    task_issues=[issue for issue in latest.get('issues',[])
                 if issue not in ('缺少资源预算','待澄清: '+GPU_BUDGET_QUESTION)]
    if 'data_source' in contract:
        task_issues=interface_issues(contract)
    if questions:
        lines.append('接下来请回答：'+str(questions[0]))
        lines.append('不确定时可以直接说“不知道，请给我建议”。')
    elif task_issues and result.get('status')!='task_defined':
        lines.append('任务接口还需整理。请补充你期望的输入、输出或效果；不用填写技术字段。')
    else:
        lines.append('需求已保存，无需重复说明。')
        if 'data_source' in contract:
            lines.append('输入、输出、数据来源和验证目标已齐全；接下来检查实验环境。')
        if GPU_BUDGET_QUESTION in (contract.get('open_questions') or []):
            lines.append('GPU 预算可等准备训练时再设置；现在不会启动训练。')
        if supported:
            lines.append('下一步：输入 /prepare 检查训练资源；这一步不会启动训练。')
        else:
            lines.append('此任务需要构建对应的训练后端。')
            lines.append('输入“开始吧”构建任务规格和接口检查，再继续生成、测试候选后端；/quit 保存退出。')
    return '\n'.join(lines)


def review_action(message,result):
    """Explicit review commands apply only to the current pending draft."""
    if result.get('pending_request') or not result.get('versions'):
        return None
    if not result['versions'][-1].get('review_required'):
        return None
    if message=='/accept':return 'accept'
    if message=='/reject':return 'reject'
    return None


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
    inputs=contract.get('inputs')
    inputs=inputs if isinstance(inputs,dict) else {}
    if inputs: lines.append('输入: '+', '.join(name+' ('+str(field.get('type'))+')' for name,field in inputs.items() if isinstance(field,dict)))
    schema=contract.get('output_schema')
    props=schema.get('properties') if isinstance(schema,dict) else {}
    props=props if isinstance(props,dict) else {}
    if props: lines.append('输出: '+', '.join(props))
    acceptance=contract.get('acceptance')
    acceptance=acceptance if isinstance(acceptance,dict) else {}
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
        questions=task_questions(contract)
        if questions: lines+=['需要你补充:']+['- '+str(q) for q in questions[:2]]
        else: lines.append('接口整理尚有问题，已保留你的描述；无需填写内部 schema 字段。')
    else: lines.append('任务接口已保存。可用 training prepare 检查执行配置。')
    from .task_adapters import training_adapter
    if not training_adapter(contract)['implementation_supported']:
        lines.append('执行后端尚未实现；/harness 生成任务执行规格。/run 当前仅支持 COCO 检测，不能执行此任务。')
        from .task_harness import configured_resources
        resources=configured_resources(contract)
        questions=resources['clarification_questions']
        if questions:lines.append('Harness 执行资源待澄清: '+questions[0]['question'])
        else:lines.append('数据来源已记录；数据内容与执行后端仍待核查。')
        if resources.get('budget_issue'):lines.append(resources['budget_issue'])
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
    parser.add_argument('action',choices=['harness-advance','harness-status','harness-generate','harness-smoke','harness-plan','start','reply','show','budget','accept','reject','recover','abandon-request','list','build','prepare','advance','watch','campaigns','audit','memory','readiness','release-status','research-init','research-step','research-status','research-watch','research-pause','research-resume','agent-status','agent-pause','agent-resume','status','logs','cancel','collect','resume','register','register-candidate','accept-candidate','candidate-acceptance-status','candidate-serving-check','candidate-infer','promote-candidate','deliver-candidate','delivery-status','select-candidate','serving-evaluate','runs','diagnose','define','validate','export','run'])
    parser.add_argument('--task-id');parser.add_argument('--session-id')
    parser.add_argument('--new-session',action='store_true',help='Explicitly create a fresh session for start, preserving all existing sessions')
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
    parser.add_argument('--from-research',action='store_true',help='Derive development records from the paused task research ledger')
    parser.add_argument('--max-latency-seconds',type=float,help='Explicit serving check target for an entire batch, including transport and decode')
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
    parser.add_argument('--harness-root',default='runs/task-harnesses',help='Durable task harness construction directory')
    parser.add_argument('--autonomous',action='store_true',help='Advance construction through generation, configured CPU checks and one repair; never starts GPU training')
    parser.add_argument('--generate-backend',action='store_true',help='Authorize one backend generation API request')
    parser.add_argument('--check-backend',action='store_true',help='Authorize the backend isolated protocol check')
    parser.add_argument('--select-development',action='store_true',help='Select from frozen paused development research before delivery; replaces --version')
    args=parser.parse_args(argv)
    if args.new_session and args.action!='start':parser.error('--new-session is only supported for start')
    if args.new_session and args.session_id:parser.error('--new-session cannot be combined with --session-id')
    if args.action in ('harness-advance','harness-status'):
        from .harness_progress import advance as advance_harness,status as harness_status,summary as harness_summary
        if not args.session_id:parser.error('harness progress requires --session-id')
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            if args.action=='harness-status':result=harness_status(session,args.harness_root)
            else:
                config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
                if args.autonomous:
                    from .harness_progress import run_until_blocked
                    result=run_until_blocked(session,config,args.harness_root,args.repository,
                                             on_progress=None if args.json else lambda message: print(message,flush=True))
                else:
                    result=advance_harness(session,config,args.harness_root,args.repository,
                                           args.generate_backend,args.check_backend)
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,subprocess.SubprocessError) as error:
            parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2) if args.json else harness_summary(result))
        return
    if args.action in ('harness-generate','harness-smoke'):
        from .harness_candidate import generate,smoke
        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        if args.action=='harness-generate':
            if not args.session_id or not args.request_id:parser.error('harness-generate requires --session-id and --request-id')
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            result=generate(session,config,args.output or 'runs/task-harnesses',args.repository,args.request_id)
        else:
            if not args.bundle:parser.error('harness-smoke requires --bundle generated candidate.json')
            candidate=json.loads(Path(args.bundle).read_text(encoding='utf-8'))
            result=smoke(candidate,config['remote'],args.repository)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='harness-plan':
        if not args.session_id:parser.error('harness-plan requires --session-id')
        from .task_harness import plan
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            result=plan(session,args.output or 'runs/task-harnesses')
        except (ValueError,KeyError,TypeError,OSError) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='select-candidate':
        if not args.session_id:parser.error('select-candidate requires --session-id')
        import sqlite3
        from .capability import Capabilities
        from .candidate_selection import select
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            registry=Capabilities(args.registry)
            try:result=select(registry,session,args.research_root)
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='delivery-status':
        if not args.session_id or not args.version:
            parser.error('delivery-status requires --session-id and original candidate --version')
        import sqlite3
        from types import SimpleNamespace
        from contextlib import closing
        from .candidate_workflow import status
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            root=Path(args.registry).resolve()
            with closing(sqlite3.connect((root/'registry.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('BEGIN')
                result=status(SimpleNamespace(root=root,db=db),session,args.version)
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='deliver-candidate':
        if not args.session_id or bool(args.version)==args.select_development or not args.dataset or args.max_latency_seconds is None:
            parser.error('deliver-candidate requires --session-id, exactly one of --version/--select-development, --dataset and --max-latency-seconds')
        import sqlite3
        from .capability import Capabilities
        from .candidate_workflow import deliver,deliver_selected
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            registry=Capabilities(args.registry)
            try:
                result=(deliver_selected(registry,session,args.dataset,args.research_root,config['remote'],args.max_latency_seconds)
                        if args.select_development else deliver(registry,session,args.version,args.dataset,args.research_root,config['remote'],args.max_latency_seconds))
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='promote-candidate':
        if not args.session_id or not args.version:
            parser.error('promote-candidate requires --session-id and --version')
        import sqlite3
        from .capability import Capabilities
        from .candidate_delivery import promote
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            registry=Capabilities(args.registry)
            try:result=promote(registry,session,args.version,args.research_root,config['remote'])
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='candidate-infer':
        if not args.task_id or not args.session_id or not args.version or not args.request_id or bool(args.sample)==bool(args.manifest):
            parser.error('candidate-infer requires --task-id, --session-id, --version, --request-id and exactly one of --sample/--manifest')
        import sqlite3
        from .capability import Capabilities
        from .candidate_inference import infer
        from .event_eval import read_document
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            if session['task_id']!=args.task_id:raise ValueError('Task ID differs from session')
            source=Path(args.sample or args.manifest).resolve()
            if args.sample:
                _,sample=read_document(source,512*1024);samples=[sample]
            else:
                if source.stat().st_size>1024*1024:raise ValueError('Manifest exceeds 1 MiB')
                samples=[json.loads(line) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            registry=Capabilities(args.registry)
            try:result=infer(registry,session,args.version,args.request_id,samples,source.parent,config['remote'])
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action=='candidate-serving-check':
        if not args.session_id or not args.version or not args.dataset or args.max_latency_seconds is None:
            parser.error('candidate-serving-check requires --session-id, --version, --dataset and --max-latency-seconds')
        import sqlite3
        from .capability import Capabilities
        from .candidate_serving import check
        try:
            session=Sessions(args.sessions,read_only=True).show(args.session_id)
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            registry=Capabilities(args.registry)
            try:result=check(registry,session,args.version,args.dataset,config['remote'],args.max_latency_seconds)
            finally:registry.close()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,sqlite3.Error) as error:parser.exit(1,str(error)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.action in ('accept-candidate','candidate-acceptance-status'):
        if not args.session_id:parser.error('Candidate acceptance requires --session-id')
        if args.action=='accept-candidate' and (not args.version or not args.dataset or not (args.development or args.from_research)):
            parser.error('accept-candidate requires --version, --dataset and either --development or --from-research')
        if args.from_research and args.development:parser.error('--from-research cannot be combined with a partial --development list')
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
                    if args.from_research:
                        from .research_history import accept as accept_research
                        result=accept_research(registry,session,args.version,args.dataset,config['remote'],args.research_root)
                    else:result=accept_candidate(registry,session,args.version,args.dataset,args.development,config['remote'])
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
                    with redirect_stdout(sys.stderr) if args.json else nullcontext():
                        return advance(current,config,args.research_root,1,args.repository,task_context=context,training_runs=args.run_store)
                result=watch(next_step,lambda:status(session_now(),args.research_root),
                             turns=args.research_watch_turns,duration=args.watch_seconds)
            else:
                from .task_readiness import inspect
                config=json.loads(Path(args.config).read_text(encoding='utf-8'))
                context=inspect(args.session_id,config,args.sessions,args.run_store,args.config)
                from contextlib import redirect_stdout, nullcontext
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
            unsupported=not result['training_adapter']['implementation_supported']
            if unsupported:
                print('缺少此任务的训练后端；当前内置训练只支持 COCO 目标检测。')
                print('下一步需要实现并验证对应后端，这是代码开发工作；继续确认需求或增加预算不能解决。')
            for action in result['suggested_actions']:
                if unsupported and action['action']=='show':continue
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
            # Resolve existing work before prompting for a goal or reading files.
            opening=store.start(args.task_id,session_id=args.session_id,new_session=args.new_session)
            if opening['status']=='goal_required':
                goal=Path(args.requirements).read_text(encoding='utf-8') if args.requirements else args.goal
                if args.interactive and (not goal or goal.strip().lower()=='describe requirements'):
                    try:goal=input('你想完成什么任务？例如：输入一张图片，判断是猫还是狗。\n> ').strip()
                    except (EOFError,KeyboardInterrupt):
                        print('已取消；未新建会话。');return
                if not goal or not goal.strip():raise ValueError('新任务需要 --goal，或使用 --interactive 描述目标。')
                # Another process may have created this task while we prompted.
                opening=store.start(args.task_id,goal,new_session=args.new_session)
            if opening['status']=='selection_required':
                if args.json:
                    print(json.dumps(opening,ensure_ascii=False,indent=2))
                else:
                    print('同一任务有多个会话，请选择要恢复的记录（按创建时间由新到旧）：')
                    for index,choice in enumerate(opening['sessions'],1):
                        goal=' '.join(str(choice['goal']).split())[:160]
                        last=' '.join(str(choice['last_user_message']).split())[:120]
                        print(str(index)+'. '+choice['session_id']+' | '+choice['status']+' | 需求版本 '+str(choice['contract_version']))
                        print('   目标：'+goal+'\n   最近输入：'+last)
                    print('可指定 --session-id 恢复；明确重新开始时使用 --new-session。')
                if not args.interactive or args.json:
                    parser.exit(2)
                while True:
                    try:selection=input('输入编号或完整 session_id；/quit 退出：').strip()
                    except (EOFError,KeyboardInterrupt):
                        print('已取消；未新建会话。');return
                    if selection=='/quit':return
                    choices=opening['sessions']
                    selected=next((choice['session_id'] for choice in choices if choice['session_id']==selection),None)
                    if selected is None and selection.isascii() and selection.isdigit() and len(selection)<8:
                        number=int(selection)
                        if 1<=number<=len(choices):selected=choices[number-1]['session_id']
                    if selected:
                        opening=store.start(args.task_id,session_id=selected)
                        break
                    print('选择无效，请输入列表中的编号或完整 session_id。')
            result=opening['session'];session=result['session_id']
            if not args.json:print(('已恢复会话。' if opening['status']=='resumed' else '已创建会话。')+'session_id: '+session,flush=True)
            if opening['status']=='created':
                if args.contract:result=store.define(session,json.loads(Path(args.contract).read_text(encoding='utf-8')))
                elif not args.offline:result=clarify(session)
            elif not args.json and any((args.goal,args.requirements,args.contract)):
                print('已保留原需求；--goal、--requirements、--contract 仅用于新建。修改需求请在会话中描述。')
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
                    storage={'sessions':args.sessions,'runs':args.run_store,'campaigns':args.campaign_store,'registry':args.registry,'plans':'runs/training-plans','research':args.research_root}
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
            print('直接用中文回答即可。不确定可以说“不知道”。/help 查看操作，/quit 保存退出。')
            show_summary=True
            prepared_contracts=set()
            intent_dialogue=[]
            shown=''
            while True:
                if show_summary:
                    shown=conversation_summary(result)
                    print(shown)
                    latest=result['versions'][-1] if result.get('versions') else {}
                    contract=latest.get('contract',{})
                    from .contracts import brief_questions,interface_issues
                    from .runner import digest
                    identity=digest(contract)
                    if ('data_source' in contract and not result.get('pending_request')
                            and not latest.get('review_required') and not brief_questions(contract)
                            and not interface_issues(contract) and identity not in prepared_contracts):
                        from .experiment_prep import prepare as prepare_experiment,summary as preparation_summary
                        try:
                            prepared_text=preparation_summary(prepare_experiment(result,args.harness_root))
                            print(prepared_text)
                            shown+='\n'+prepared_text
                            prepared_contracts.add(identity)
                        except (ValueError,OSError) as error:
                            print('实验准备未完成：'+str(error))
                show_summary=False
                try:
                    message=input('\n> ').strip()
                except (EOFError, KeyboardInterrupt):
                    print('\n会话已保存。session_id: '+session)
                    break
                if message=='/quit':
                    print('会话已保存。session_id: '+session)
                    break
                if message=='/contract':
                    current=store.show(session)
                    latest=current['versions'][-1] if current['versions'] else {}
                    contract={'active_contract':latest['contract'],'proposed_contract':latest['proposed_contract'],'draft_version':latest['version']} if latest.get('review_required') else latest.get('contract',{})
                    shown=json.dumps(contract,ensure_ascii=False,indent=2)
                    print(shown)
                    continue
                if message and not message.startswith('/'):
                    from .intent import resolve as resolve_intent
                    try:
                        result=store.show(session)
                        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
                        decision=resolve_intent(message,result,config,args.harness_root,shown,intent_dialogue)
                    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
                        print('未能可靠判断本次意图，未执行操作。请重述，或用 /help 查看显式命令。原因：'+str(error))
                        continue
                    intent_dialogue.append({'user':message,'decision':decision})
                    intent=decision['action']
                    if intent=='data':
                        shown='当前尚未接入公开数据搜索和下载执行器；本次未下载数据，也未生成后端。可以提供已下载的数据路径继续准备。'
                        print(shown)
                        continue
                    if intent in ('explain','stop'):
                        shown=(decision['reply'] if intent=='explain' else '已停止继续推进；已提交的远端作业不会因此取消。')
                        print(shown)
                        continue
                    if intent!='clarify':
                        message={'advance':'/harness-next','generate':'/harness-generate',
                                 'check':'/harness-check','status':'/harness-status',
                                 'accept':'/accept','reject':'/reject'}[intent]
                action=review_action(message,result)
                if action:
                    result=getattr(store,action)(session,result['versions'][-1]['version'])
                    show_summary=True
                    continue
                if message in ('/accept','/reject'):
                    print('当前没有待确认的新需求，直接描述你想修改的内容即可。')
                    continue
                if interactive_action(message,session,args):
                    result=store.show(session)
                    continue
                if message=='/show':
                    result=store.show(session)
                    shown=summary(result)
                    print(shown)
                elif message:
                    result=clarify(session,message)
                    show_summary=True
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
