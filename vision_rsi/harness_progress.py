"""Resumable task-harness construction; candidate generation is not training."""
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from .campaign import lease
from .contracts import issues
from .runner import atomic_json, digest


def _location(session, root):
    session_id = session.get('session_id')
    if not isinstance(session_id, str) or not re.fullmatch('[0-9a-f]{32}', session_id):
        raise ValueError('Invalid session ID')
    if session.get('pending_request') or not session.get('versions'):
        raise ValueError('先完成或恢复需求澄清，再构建 harness。')
    latest = session['versions'][-1]
    if latest.get('review_required'):
        raise ValueError('先确认当前需求草案，再构建 harness。')
    contract = latest['contract']
    blockers = [item for item in issues(contract)
                if '预算' not in item and not item.startswith('待澄清:')]
    if blockers:
        raise ValueError('任务接口尚不完整：' + '; '.join(blockers))
    binding = {'session_id': session_id, 'task_id': session['task_id'],
               'contract_sha256': digest(contract)}
    return Path(root).resolve() / session_id / binding['contract_sha256'], binding


def _load(path, binding):
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('format') != 'vision-rsi/harness-progress/v1' or state.get('binding') != binding:
        raise ValueError('Harness progress binding changed; retained for inspection')
    return state


def status(session, root):
    folder, binding = _location(session, root)
    path = folder / 'progress.json'
    if not path.exists():
        return {'status': 'not_started', 'binding': binding, 'progress_path': str(path),
                'training_performed': False, 'quality_verified': False,
                'next_step': '输入“开始吧”构建任务规格和接口检查。'}
    return dict(_load(path, binding), progress_path=str(path), read_only=True)


def advance(session, config, root, repository='.', generate_backend=False, check_backend=False):
    """Build/check local artifacts, then at most one generation and one smoke.

    Explicit generation/check commands authorize their named operation. Otherwise
    honor the existing research permission switches. Unknown remote/API outcomes
    are terminal here: never turn a new chat message into a duplicate request.
    """
    from .harness import build
    from .harness_candidate import generate, smoke
    from .task_harness import plan
    from .candidates import Candidates

    folder, binding = _location(session, root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'progress.json'
    completed = []
    with lease(folder / 'progress.lock', owner='Harness construction'):
        if path.exists():
            state = _load(path, binding)
            # Identical requirements may acquire another conversational version.
            # Reuse the original snapshot and request IDs instead of paying again.
            frozen = state['session_snapshot']
            if (frozen.get('session_id') != binding['session_id']
                    or frozen.get('task_id') != binding['task_id']
                    or digest(frozen['versions'][-1]['contract']) != binding['contract_sha256']):
                raise ValueError('Frozen harness session changed')
        else:
            frozen = {key: session[key] for key in ('session_id', 'task_id', 'versions')}
            frozen['versions'] = [session['versions'][-1]]
            state = {'format': 'vision-rsi/harness-progress/v1', 'binding': binding,
                     'session_snapshot': frozen, 'status': 'building', 'attempts': [],
                     'training_performed': False, 'quality_verified': False,
                     'gpu_dispatch_ready': False}
            atomic_json(path, state)

        def finish(stage, next_step, **values):
            state.update(status=stage, next_step=next_step, **values)
            atomic_json(path, state)
            return dict(state, progress_path=str(path), completed_this_turn=completed)

        # These idempotent builders verify existing artifact hashes on every use.
        requirements = plan(frozen, folder / 'plans')
        interface = build(frozen, folder / 'interfaces')
        if 'interface' not in state:
            completed.extend(['已生成任务执行规格', '已构建独立输入输出校验程序'])
        state.update(plan=requirements, interface=interface)
        command = [sys.executable, '-B', str(Path(interface['directory']) / 'harness.py'), 'check']
        checked = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
        if checked.returncode:
            return finish('interface_check_failed', '接口检查失败；查看保存的检查输出后修复需求。',
                          interface_check={'returncode': checked.returncode,
                                           'stdout': checked.stdout[-8000:], 'stderr': checked.stderr[-8000:]})
        receipt = json.loads(checked.stdout)
        if (receipt.get('status') != 'interface_checked' or receipt.get('model_available') is not False
                or receipt.get('task_id') != binding['task_id']
                or receipt.get('contract_version') != frozen['versions'][-1]['version']):
            raise ValueError('Unexpected interface check receipt')
        if 'interface_check' not in state:
            completed.append('已运行输入输出示例检查并通过')
        state['interface_check'] = receipt
        atomic_json(path, state)
        if not requirements['missing_backend']:
            return finish('existing_backend_available', '已有兼容训练后端；输入 /prepare 检查数据、权重和训练预算。')

        research = config.get('research') or {}
        if not isinstance(research,dict):raise ValueError('research 配置必须是对象。')
        if generate_backend:state['generation_authorized']=True
        if check_backend:state['checks_authorized']=True
        generation_allowed = state.get('generation_authorized') or research.get('allow_candidate_writes') is True
        checks_allowed = state.get('checks_authorized') or research.get('allow_candidate_checks') is True
        feedback=None
        resume_attempt=None
        if not state.get('candidate') and state['attempts'] and state['attempts'][-1]['status']=='reserved':
            original=state['attempts'][-1]
            database=folder/'generation'/'generation.sqlite3'
            received=False
            if database.is_file():
                db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
                try:
                    row=db.execute('SELECT state FROM requests WHERE id=?',(original['request_id'],)).fetchone()
                    received=bool(row and row[0]=='responded')
                finally:db.close()
            if received:
                cached=folder/'generation'/'requests'/original['request_id']/'candidate.json'
                if cached.is_file():
                    state['candidate']=json.loads(cached.read_text(encoding='utf-8'))
                    original['status']='completed'
                    completed.append('已恢复上次保存的候选源码，无需重复调用 API')
                else:resume_attempt=original
        if state.get('smoke',{}).get('status')=='backend_protocol_smoke_failed':
            if generation_allowed and len(state['attempts'])<2:
                state['attempts'][-1]['smoke']=state.pop('smoke')
                state['attempts'][-1]['candidate']=state.pop('candidate')
                state.pop('smoke_attempt',None)
                state.pop('candidate_source',None)
                state['attempts'][-1]['status']='rejected'
        if not state.get('candidate'):
            attempts = state['attempts']
            if attempts:
                attempt = attempts[-1]
                if attempt['status'] == 'reserved' and resume_attempt is None:
                    return finish('generation_uncertain', '上次后端生成结果不确定，已保留原请求；不会自动重发。')
                if attempt['status']=='failed':
                    return finish('generation_failed', '生成响应未通过检查；查看保存的失败原因，修复后使用独立生成命令继续。')
                if attempt['status']=='rejected':
                    if len(attempts)>=2:
                        return finish('repair_limit_reached','两次候选尝试均未完成验证，已停止；请查看失败证据，避免反复消耗 API。')
                    previous=folder/'generation'/'requests'/attempt['request_id']/'response.json'
                    feedback={'failure':attempt.get('result') or attempt.get('smoke')}
                    if previous.is_file():
                        response=json.loads(previous.read_text(encoding='utf-8'))
                        content=response.get('content')
                        if isinstance(content,str):
                            feedback.update(previous_response=content[:50000],response_truncated=len(content)>50000)
                if attempt['status'] == 'not_dispatched':
                    if len(attempts)>=2:
                        return finish('repair_limit_reached','已达到两次生成尝试上限；请检查 API 准入失败记录。')
                    if not generate_backend:
                        return finish('generation_not_dispatched', '上次生成请求未发送；修复 API 准入配置后输入“生成后端”显式重试。')
            if not generation_allowed and resume_attempt is None:
                return finish('awaiting_generation', '输入“生成后端”让模型编写候选实现（调用 API）；'
                              '或在配置中启用 research.allow_candidate_writes 后输入“继续”。')
            # Validate local prerequisites before reserving the generation step.
            from .llm import OpenAICompatibleClient, LLMNotDispatched
            try:
                if resume_attempt is None:OpenAICompatibleClient(config.get('llm', {})).validate_config()
                store = Candidates(folder / 'generation' / 'candidates', repository)
                try:
                    base = store.base()
                finally:
                    store.close()
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                return finish('generation_prerequisite_missing', str(error), prerequisite_error=type(error).__name__)
            if resume_attempt is not None:
                if base!=resume_attempt['base_revision']:
                    return finish('generation_prerequisite_missing','原响应已收到，但源码版本已变化；保留原记录，请检查原候选基线。')
                attempt=resume_attempt
                feedback=attempt.get('feedback')
                request_id=attempt['request_id']
            else:
                request_id = 'backend-' + digest({'binding': binding, 'base': base,'attempt':len(attempts)+1})[:24]
                attempt = {'request_id': request_id, 'base_revision': base, 'status': 'reserved','feedback':feedback}
                state['attempts'].append(attempt)
            atomic_json(path, state)
            try:
                candidate = generate(frozen, config, folder / 'generation', repository, request_id,feedback=feedback)
            except LLMNotDispatched:
                attempt['status'] = 'not_dispatched'
                return finish('generation_not_dispatched', '后端生成请求未发送；修复 API 额度与配置后输入“生成后端”显式重试，原记录已保留。')
            except (ValueError, TypeError, KeyError) as error:
                attempt.update(status='failed', error=type(error).__name__)
                return finish('generation_failed', '后端生成未完成；原请求记录已保留，未自动重试。')
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                attempt['error'] = type(error).__name__
                return finish('generation_uncertain', '后端生成结果不确定；原请求已保留，未自动重发。')
            if candidate['status'] != 'backend_candidate_created':
                attempt.update(status='rejected', result=candidate)
                return finish('generation_failed', '后端候选未通过静态检查：' + candidate.get('reason', candidate['status'])+
                              ('。输入“继续”将根据错误修复一次。' if len(attempts)<2 else '。已达到两次尝试上限。'))
            attempt['status'] = 'completed'
            state['candidate'] = candidate
            completed.append('已生成候选后端源码并保存为独立 Git 候选')
            atomic_json(path, state)

        candidate = state['candidate']
        if (candidate.get('status')!='backend_candidate_created'
                or Path(candidate['store']).resolve()!=(folder/'generation'/'candidates').resolve()):
            raise ValueError('Candidate receipt outside the bound harness workflow')
        # A cached receipt must still refer to intact candidate source.
        store = Candidates(candidate['store'], repository)
        try:
            record, _ = store.source_files(candidate['candidate_id'])
        finally:
            store.close()
        from .harness_candidate import validate_backend
        context=record['identity']['context']
        if (context.get('request_id')!=state['attempts'][-1]['request_id']
                or context.get('harness_plan_id')!=requirements['plan_id']
                or record['identity']['base_revision']!=state['attempts'][-1]['base_revision']
                or record['git_revision']!=candidate['git_revision']
                or validate_backend(record['identity']['proposal'])!=candidate['module']):
            raise ValueError('Candidate does not match the bound task and generation request')
        state['candidate_source'] = record['checkout']
        if state.get('smoke_attempt', {}).get('status') == 'reserved':
            check_id=digest({'candidate':candidate['candidate_id'],'kind':'backend-protocol-smoke-v1'})[:32]
            evidence_path=Path(candidate['store'])/candidate['candidate_id']/'checks'/(check_id+'.json')
            evidence=json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.is_file() else {}
            if not evidence or evidence.get('status')=='reserved':
                return finish('smoke_uncertain', '上次隔离测试结果不确定；保留原测试记录，不重复执行。')
            # Candidates.check verifies and returns this completed receipt before
            # any remote call. Preserve its original execution context on resume.
            state['smoke']=smoke(candidate,evidence['remote'],repository)
            state['smoke_attempt']['status']='completed'
            completed.append('已恢复保存的隔离测试回执，无需重复执行')
        if not state.get('smoke'):
            if not checks_allowed:
                return finish('awaiting_smoke', '输入“测试后端”在配置的远端隔离环境检查候选代码；'
                              '或启用 research.allow_candidate_checks 后输入“继续”。')
            remote = config.get('remote') or {}
            if not isinstance(remote,dict):raise ValueError('remote 配置必须是对象。')
            if not remote.get('ssh_host') or not remote.get('workspace'):
                return finish('remote_required', '候选源码已保存；请配置 remote.ssh_host 和 remote.workspace 后输入“测试后端”。')
            state['smoke_attempt'] = {'status': 'reserved'}
            atomic_json(path, state)
            try:
                report = smoke(candidate, remote, repository)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                state['smoke_attempt']['error'] = type(error).__name__
                return finish('smoke_uncertain', '隔离测试未返回可确认结果；原测试已保留，不自动重复执行。')
            state['smoke'] = report
            state['smoke_attempt']['status'] = 'completed'
            completed.append('已执行候选后端隔离协议测试')
            atomic_json(path, state)
        if state['smoke']['status'] != 'backend_protocol_smoke_passed':
            return finish('smoke_failed', '候选未通过隔离协议测试；'+
                          ('输入“继续”按测试证据修复一次。' if len(state['attempts'])<2 else '已达到两次候选尝试上限，停止自动修复。'))
        return finish('backend_protocol_checked',
                      '候选协议检查已通过。下一步需绑定真实数据、验证各阶段并接入计费调度；尚不能提交此候选训练。',
                      remaining_requirements=requirements['resource_requirements'])


def summary(result):
    labels={'not_started':'尚未构建','awaiting_generation':'接口检查通过，待生成后端',
            'awaiting_smoke':'候选源码已生成，待隔离测试','remote_required':'候选源码已生成，缺少远端配置',
            'generation_prerequisite_missing':'生成前置条件待补充','generation_failed':'候选生成或校验失败',
            'generation_not_dispatched':'生成请求未发送','generation_uncertain':'生成结果待核实',
            'smoke_uncertain':'隔离测试结果待核实','smoke_failed':'隔离测试未通过',
            'backend_protocol_checked':'候选协议检查通过','existing_backend_available':'已有兼容训练后端',
            'interface_check_failed':'接口检查未通过','repair_limit_reached':'已达到候选修复上限'}
    lines = ['Harness 进度：' + labels.get(result['status'],result['status'])]
    lines.extend('- ' + item for item in result.get('completed_this_turn', []))
    if not result.get('completed_this_turn') and result['status'] != 'not_started':
        lines.append('已复用保存的构建进度。')
    if result.get('interface'):
        lines.append('接口校验程序：' + result['interface']['directory'])
    if result.get('candidate_source'):
        lines.append('候选源码：' + result['candidate_source'])
    lines.append('下一步：' + result['next_step'])
    lines.append('进度记录：' + result['progress_path'])
    lines.append('尚未进行训练或模型效果验收。')
    return '\n'.join(lines)
