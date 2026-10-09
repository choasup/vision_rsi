"""Bounded live-LLM/SSH demo using explicitly synthetic vision scores."""
import html
import json
import math
import os
from pathlib import Path
import time

from .llm import OpenAICompatibleClient
from .remote import job_request
from .research import RECIPES, evaluate, fingerprint
from .runner import atomic_json, digest, revision


def parse_proposal(content, remaining):
    text = content.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    value = json.loads(text)
    index = value['candidate_index']
    if isinstance(index, bool) or not isinstance(index, int) or index not in remaining:
        raise ValueError('LLM selected an unavailable candidate')
    hypothesis = value['hypothesis']
    if not isinstance(hypothesis, str) or not 1 <= len(hypothesis) <= 2000:
        raise ValueError('Invalid hypothesis')
    return index, hypothesis


def render(state, directory):
    rows = []
    for i, row in enumerate(state['experiments']):
        score = row.get('metric_value', '—')
        rows.append('<tr>' + ''.join('<td>' + html.escape(str(x)) + '</td>' for x in [
            i, row['recipe']['learning_rate_scale'], row['recipe']['augmentation_strength'],
            row['status'], score, row['hypothesis']]) + '</tr>')
    values = [r['metric_value'] for r in state['experiments'] if 'metric_value' in r]
    baseline = values[0] if values else None
    best = max(values) if values else None
    tokens = sum(x.get('usage', {}).get('total_tokens', 0) for x in state['llm_calls'])
    document = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Vision RSI Demo</title>
<style>body{font:16px system-ui;background:#0b1220;color:#e2e8f0;margin:0;padding:40px;line-height:1.6}
main{max-width:1100px;margin:auto}h1{font-size:36px;margin-bottom:8px}.badge{color:#fbbf24}
.cards{display:flex;gap:16px;margin:28px 0}.card{background:#182438;padding:20px;border-radius:12px;flex:1}
b{display:block;font-size:28px;color:#5eead4}table{width:100%;border-collapse:collapse;background:#182438}
th,td{text-align:left;padding:12px;border-bottom:1px solid #334155}small{color:#94a3b8}code{color:#7dd3fc}</style><main>
<h1>Vision RSI Agent · Live Demo</h1><div class="badge">真实 DeepSeek + 真实 SSH · 合成视觉指标 · 无 COCO 训练</div>
<p>LLM 读取实验历史 → 选择白名单配方 → 确定性校验 → 远端 CPU 执行 → 回收指标 → 更新研究记录</p>
'''
    cards = [('已记录实验', len(state['experiments'])), ('基线合成分数', baseline),
             ('最佳合成分数', best), ('API tokens', tokens)]
    document += '<div class="cards">' + ''.join('<div class="card">' + title + '<b>' + str(value) + '</b></div>' for title, value in cards) + '</div>'
    document += '<table><tr><th>实验</th><th>LR 倍率</th><th>增强强度</th><th>状态</th><th>合成分数</th><th>选择理由</th></tr>' + ''.join(rows) + '</table>'
    document += '<p>预算：最多 3 个实验、2 次 LLM 请求，每次最多 1024 输出 tokens；每个远端任务硬超时 15 秒，隐藏 CUDA。实际 GPU 小时为 0。</p>'
    document += '<p>固定候选空间，不执行 LLM 生成的代码。模拟分数变化不能证明真实检测提升或 RSI 有效。</p>'
    document += '<small>运行 ID: ' + html.escape(state['run_id']) + ' · Git: ' + html.escape(state['identity']['git_revision']) + '</small></main></html>'
    (directory / 'report.html').write_text(document, encoding='utf-8')


def demo(config, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'demo.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        path = directory / 'demo-state.json'
        identity = {'git_revision': revision(), 'config_hash': digest(config),
                    'source_hash': digest({p.name: p.read_text(encoding='utf-8-sig') for p in Path(__file__).parent.glob('*.py')})}
        if path.exists():
            state = json.loads(path.read_text())
            if state['identity'] != identity:
                raise ValueError('Demo source/config/revision changed; use a new directory')
        else:
            import uuid
            state = {'run_id': 'demo-' + uuid.uuid4().hex[:12], 'identity': identity,
                     'synthetic_metrics': True, 'experiments': [], 'llm_calls': []}
        def checkpoint():
            atomic_json(path, state)
            render(state, directory)
        checkpoint()
        while True:
            pending = next((r for r in state['experiments'] if r['status'] in ('planned', 'queued', 'running') or (r['status'] == 'completed' and 'metric_value' not in r)), None)
            if pending is None:
                if len(state['experiments']) >= 3:
                    break
                used = {r['candidate_index'] for r in state['experiments']}
                remaining = [i for i in range(len(RECIPES)) if i not in used]
                if not state['experiments']:
                    index, hypothesis = 0, '固定基线配方；未使用 LLM。'
                else:
                    if any(c['status'] == 'requesting' for c in state['llm_calls']):
                        raise RuntimeError('Uncertain previous API call; not retrying automatically')
                    call = next((c for c in state['llm_calls'] if c['status'] == 'received'), None)
                    if call is None:
                        if len(state['llm_calls']) >= 2:
                            break
                        call = {'status': 'requesting'}
                        state['llm_calls'].append(call)
                        checkpoint()
                        prompt = {'instruction': 'This is a synthetic vision research demo. Select one remaining candidate based on history. Reply JSON only: {"candidate_index": integer, "hypothesis": "brief Chinese explanation"}. Do not claim real training gains.',
                                  'candidates': {i: RECIPES[i] for i in remaining},
                                  'history': state['experiments']}
                        response = OpenAICompatibleClient(config['llm']).complete(
                            [{'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)}], max_tokens=1024)
                        call.update(status='received', **response)
                        checkpoint()
                    try:
                        index, hypothesis = parse_proposal(call['content'], remaining)
                    except (ValueError, KeyError, TypeError):
                        call['status'] = 'rejected'
                        checkpoint()
                        raise ValueError('LLM proposal rejected; no unvalidated execution') from None
                recipe = RECIPES[index]
                code = ('import json; recipe=' + repr(recipe) + '; ' +
                        'import hashlib; fingerprint=lambda r:hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(); ' +
                        'noise=int(hashlib.sha256((str(42)+":"+fingerprint(recipe)).encode()).hexdigest()[:8],16)%101/1000; ' +
                        'value=round(31-(recipe["learning_rate_scale"]-0.5)**2-(recipe["augmentation_strength"]-0.8)**2+noise,4); ' +
                        'print(json.dumps({"synthetic":True,"metric_value":value,"recipe_hash":fingerprint(recipe)}))')
                pending = {'job_id': state['run_id'] + '-' + str(len(state['experiments'])),
                           'candidate_index': index, 'recipe': recipe, 'hypothesis': hypothesis,
                           'status': 'planned', 'spec': {'argv': [config['remote'].get('python', 'python3'), '-c', code], 'timeout_seconds': 15}}
                state['experiments'].append(pending)
                if len(state['experiments']) > 1:
                    call['status'] = 'consumed'
                checkpoint()
            job_request(config['remote'], 'submit', pending['job_id'], pending['spec'])
            deadline = time.monotonic() + 45
            while True:
                result = job_request(config['remote'], 'status', pending['job_id'])
                pending['status'] = result['status']
                pending['remote_result'] = result
                checkpoint()
                if result['status'] not in ('queued', 'running'):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Polling deadline; rerun same directory to resume')
                time.sleep(0.5)
            if pending['status'] == 'completed':
                logs = job_request(config['remote'], 'logs', pending['job_id'])['log']
                pending['remote_log'] = logs
                metric = json.loads(logs.strip())
                value = metric['metric_value']
                if (metric.get('synthetic') is not True or metric.get('recipe_hash') != fingerprint(pending['recipe'])
                    or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value != evaluate(pending['recipe'], 42)):
                    pending['status'] = 'invalid_result'
                    checkpoint()
                    raise ValueError('Remote fixture metric validation failed')
                pending['metric_value'] = value
            checkpoint()
            print('Experiment ' + pending['job_id'] + ': ' + pending['status'], flush=True)
        return {'report': str((directory / 'report.html').resolve()),
                'experiments': len(state['experiments']), 'llm_calls': len(state['llm_calls']),
                'synthetic_metrics': True}
    finally:
        lock.unlink()
