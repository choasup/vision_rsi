"""Standard-library-only deterministic mock research loop."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def revision():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def run(config, directory):
    if config['mode'] != 'mock':
        raise ValueError('Real execution is not implemented; use mode=mock.')
    budget = config['budget_gpu_hours']
    limit = config['max_experiments']
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0:
        raise ValueError('budget_gpu_hours must be finite and nonnegative')
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError('max_experiments must be a nonnegative integer')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / 'state.json'
    identity = {'config_hash': digest(config), 'git_revision': revision()}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['identity'] != identity:
            raise ValueError('Configuration or Git revision changed; start a new run directory.')
    else:
        state = {'identity': identity, 'mode': 'mock', 'experiments': [], 'spent_gpu_hours': 0}
    # Each synthetic experiment costs one simulated GPU-hour. Admission occurs first.
    while len(state['experiments']) < limit and state['spent_gpu_hours'] + 1 <= budget:
        index = len(state['experiments'])
        candidate = {'id': f'exp-{index:04d}', 'parent_revision': identity['git_revision'],
                     'change': ['baseline', 'learning_rate_scale=0.5', 'augmentation_strength=0.8'][index % 3]}
        noise = int(digest({'seed': config['seed'], 'candidate': index})[:8], 16) % 100
        candidate.update({'status': 'completed', 'synthetic_box_ap': round(30 + noise / 100, 2),
                          'simulated_gpu_hours': 1, 'analysis': 'Synthetic fixture; no COCO evaluation performed.'})
        state['experiments'].append(candidate)
        state['spent_gpu_hours'] += 1
        atomic_json(state_path, state)
    if not state_path.exists():
        atomic_json(state_path, state)
    return state


def doctor(config):
    return {'mode': config['mode'], 'ssh_available': bool(__import__('shutil').which('ssh')),
            'llm_model_configured': bool(config['llm']['model']),
            'llm_base_url_configured': bool(config['llm']['base_url']),
            'api_key_present': bool(os.environ.get(config['llm']['api_key_env'])),
            'remote_configured': bool(config['remote']['ssh_host'] and config['remote']['workspace']),
            'real_training_implemented': False, 'real_api_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'doctor', 'llm-check', 'compare', 'remote-check', 'job-submit', 'job-status', 'job-logs', 'job-cancel', 'demo', 'research-import', 'research-event', 'research-view'])
    parser.add_argument('--config', default='config.example.json')
    parser.add_argument('--run-dir', default='runs/demo')
    parser.add_argument('--job-id', default='cpu-smoke-001')
    parser.add_argument('--job-spec', help='JSON file with argv and timeout_seconds (CPU only)')
    parser.add_argument('--source', help='Demo state JSON to import')
    parser.add_argument('--event-file', help='JSON with key, kind, payload')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if args.command.startswith('research-'):
        from .ledger import Ledger, import_demo
        from .observatory import dashboard
        ledger = Ledger(args.run_dir)
        if args.command == 'research-import':
            import_demo(ledger, args.source)
        elif args.command == 'research-event':
            event = json.loads(Path(args.event_file).read_text(encoding='utf-8'))
            ledger.append(event['key'], event['kind'], event['payload'])
        result = {'dashboard': dashboard(ledger), 'events': len(ledger.events())}
    elif args.command == 'demo':
        from .demo import demo
        result = demo(config, args.run_dir)
    elif args.command.startswith('job-'):
        from .remote import job_request
        spec = None
        if args.command == 'job-submit':
            spec = json.loads(Path(args.job_spec).read_text(encoding='utf-8')) if args.job_spec else {
                'argv': [config['remote'].get('python', 'python3'), '-c', 'import time; print("CPU smoke started", flush=True); time.sleep(2); print("CPU smoke completed")'],
                'timeout_seconds': 15}
        result = job_request(config['remote'], args.command.removeprefix('job-'), args.job_id, spec)
    elif args.command == 'remote-check':
        from .remote import probe
        result = probe(config['remote'])
        directory = Path(args.run_dir)
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(directory / 'remote-environment.json', result)
    elif args.command == 'compare':
        from .research import compare
        result = compare()
        directory = Path(args.run_dir)
        directory.mkdir(parents=True, exist_ok=True)
        result['git_revision'] = revision()
        atomic_json(directory / 'comparison.json', result)
    elif args.command == 'llm-check':
        from .llm import OpenAICompatibleClient
        result = OpenAICompatibleClient(config['llm']).complete(
            [{'role': 'user', 'content': 'Reply with OK only.'}], max_tokens=128)
    else:
        result = doctor(config) if args.command == 'doctor' else run(config, args.run_dir)
    print(json.dumps(result, indent=2))
