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
    """Identify this controller, independently of the caller's working directory.

    Installed wheels have no Git checkout. Their explicit source digest must not
    be mistaken for a commit from an unrelated repository in the current dir.
    """
    package=Path(__file__).resolve().parent
    repository=package.parent
    if (repository/'.git').exists():
        return subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],
                                       text=True,stderr=subprocess.DEVNULL).strip()
    sources={path.name:hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(package.iterdir()) if path.is_file() and path.suffix in ('.py','.html')}
    return 'source-sha256:'+digest(sources)


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
    """Local-only configuration checks; never claim remote/API/effect validation."""
    if not isinstance(config,dict):raise ValueError('Doctor config must be an object')
    llm=config.get('llm');remote=config.get('remote')
    llm=llm if isinstance(llm,dict) else {}
    remote=remote if isinstance(remote,dict) else {}
    env_name=llm.get('api_key_env')
    from .credentials import read_key
    key,key_scope=read_key(env_name)
    key_present=bool(key)
    llm_valid=False
    try:
        from .llm import OpenAICompatibleClient
        OpenAICompatibleClient(llm).validate_config()
        llm_valid=True
    except (ValueError,TypeError,AttributeError):pass
    remote_valid=False
    try:
        from .remote import ssh_argv
        ssh_argv(remote)
        from pathlib import PurePosixPath
        workspace=remote.get('workspace')
        remote_valid=isinstance(workspace,str) and PurePosixPath(workspace).is_absolute() and not any(c in workspace for c in ('\x00','\n','\r'))
    except (ValueError,TypeError):pass
    controller_valid=True;controller_limit=None
    try:
        from .controller_budget import configured_limit
        controller_limit=configured_limit(config)
    except ValueError:controller_valid=False
    ssh_available=bool(__import__('shutil').which('ssh'))
    return {'mode':config.get('mode'),'ssh_available':ssh_available,
            'llm_model_configured':isinstance(llm.get('model'),str) and bool(llm['model'].strip()),
            'llm_base_url_configured':isinstance(llm.get('base_url'),str) and bool(llm['base_url']),
            'api_key_present':key_present,'api_key_scope':key_scope,'llm_configuration_valid':llm_valid,
            'remote_configured':remote_valid,'real_training_implemented':True,
            'training_scope':'Fixed COCO single-image baseline and bounded recipe experiments; general harness/model adaptation is incomplete.',
            'checks_performed':['local_configuration_only'],'read_only':True,
            'configuration_ready':bool(ssh_available and remote_valid and llm_valid and controller_valid),
            'controller_configuration_valid':controller_valid,'controller_tool_attempt_limit':controller_limit,
            'real_api_tested':False,'remote_connectivity_tested':False,'training_performed':False,
            'task_budget_checked':False,'task_effect_verified':False,'release_verified':False,
            'next_steps':['training show --session-id SESSION_ID: inspect task contract and unresolved requirements',
                          'training prepare --session-id SESSION_ID --config CONFIG: validate task budget and compile a plan',
                          'remote-check and llm-check are separate explicit live probes'],
            'scope':'Configuration readiness alone does not authorize training or prove task quality, live service access, or release readiness.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'doctor', 'llm-check', 'compare', 'remote-check', 'job-submit', 'job-status', 'job-logs', 'job-cancel', 'demo', 'research-import', 'research-event', 'research-view', 'research-step', 'serve', 'training', 'test', 'capabilities'])
    parser.add_argument('--config', default='config.example.json')
    parser.add_argument('--run-dir', default='runs/demo')
    parser.add_argument('--job-id', default='cpu-smoke-001')
    parser.add_argument('--job-spec', help='JSON job spec: argv, timeout_seconds; GPU requires gpu_devices and gpu_hours_budget')
    parser.add_argument('--source', help='Demo state JSON to import')
    parser.add_argument('--event-file', help='JSON with key, kind, payload')
    parser.add_argument('--steps', type=int, default=1)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--task', help='Training task specification JSON')
    parser.add_argument('--task-id')
    parser.add_argument('--input')
    parser.add_argument('--output')
    parser.add_argument('--input-dir')
    parser.add_argument('--manifest')
    parser.add_argument('--output-dir')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--version')
    parser.add_argument('--registry', default='runs/capabilities')
    args = parser.parse_args()
    config = {} if args.command in ('training','test','capabilities') else json.loads(Path(args.config).read_text(encoding='utf-8'))
    if args.command in ('training', 'test', 'capabilities'):
        from .capability import Capabilities
        registry = Capabilities(args.registry)
        try:
            if args.command == 'training':
                result = registry.train(args.task)
            elif args.command == 'test':
                if sum(bool(x) for x in (args.input,args.input_dir,args.manifest)) != 1:
                    parser.error('test requires exactly one of --input, --input-dir, --manifest')
                if args.input_dir or args.manifest:
                    from .batch import batch, input_rows
                    if not args.output_dir: parser.error('batch inference requires --output-dir')
                    result = batch(registry,args.task_id,input_rows(args.manifest,args.input_dir),args.output_dir,args.version,args.resume)
                else:
                    result = registry.infer(args.task_id, args.input, args.version)
                if args.output:
                    atomic_json(Path(args.output), result)
            else:
                result = registry.list()
        finally:
            registry.close()
    elif args.command == 'serve':
        from .app import serve
        serve(config, args.run_dir, str(Path.cwd()), args.port)
        return
    elif args.command == 'research-step':
        from .controller import research_step
        result = research_step(config, args.run_dir, args.steps)
    elif args.command.startswith('research-'):
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
