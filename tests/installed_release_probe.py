"""Run with the freshly installed interpreter; never import the source package."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--wheel', required=True)
    parser.add_argument('--expected-version')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    wheel = Path(args.wheel).resolve()
    with tempfile.TemporaryDirectory(prefix='vision-rsi-installed-') as directory:
        os.chdir(directory)
        import vision_rsi
        from vision_rsi.runner import revision
        package = Path(vision_rsi.__file__).resolve().parent
        assert 'site-packages' in package.parts, package
        installed_version=importlib.metadata.version('vision-rsi-agent')
        if args.expected_version is not None:
            assert installed_version==args.expected_version, 'Installed package version differs from requested release'
        checked = {}
        source_files = {p.relative_to(repo/'vision_rsi') for p in (repo/'vision_rsi').rglob('*') if p.suffix in ('.py', '.html')}
        installed_files = {p.relative_to(package) for p in package.rglob('*') if p.suffix in ('.py', '.html')}
        assert source_files == installed_files, 'Installed package file set differs from source'
        for relative in sorted(source_files):
            expected = hashlib.sha256((repo/'vision_rsi'/relative).read_bytes()).hexdigest()
            assert hashlib.sha256((package/relative).read_bytes()).hexdigest() == expected, relative
            checked[str(relative)] = expected
        commands = [['--help'], ['training', 'memory', '--help'], ['test', '--help'],
                    ['training', 'readiness', '--help'], ['evaluate-events', '--help'],
                    ['experiment-request', '--help'], ['training','research-status','--help'],
                    ['training','research-watch','--help']]
        for command in commands:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'vision_rsi']+command,
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            assert result.returncode == 0, result.stderr
        sys.path.insert(0, str(repo/'tests'))
        names = ['test_doctor', 'test_research_memory', 'test_strategy_context', 'test_training_shell',
                 'test_campaign', 'test_campaign_audit', 'test_policy_audit', 'test_paired_study',
                 'test_cpu_runtime', 'test_training_runtime', 'test_serving_state', 'test_serving_acceptance',
                 'test_remote_capability', 'test_controller_budget', 'test_watch', 'test_video_runtime',
                 'test_filesystem', 'test_experiments', 'test_executable_harness', 'test_not_dispatched',
                 'test_task_adapters', 'test_task_readiness', 'test_event_eval',
                 'test_coco_train', 'test_training_preflight', 'test_batch', 'test_experiment_observe',
                 'test_study_resources', 'test_cli_help', 'test_harness', 'test_controller','test_task_research','test_release_status','test_planning_budget','test_research_watch','test_research_training']
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        with (output/'installed-tests.log').open('w', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        # A test must not have replaced the package with the source checkout.
        assert Path(sys.modules['vision_rsi'].__file__).resolve().parent == package
        evidence = dict(source_revision=subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                        installed_package=str(package), installed_version=installed_version,
                        expected_version=args.expected_version, controller_identity=revision(), cwd=directory,
                        tested_modules=names, tests_run=result.testsRun, passed=result.wasSuccessful(),
                        source_hashes=checked, module_cli_commands=commands,
                        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                        remote_called=False, llm_called=False, gpu_used=False,
                        scope='Local installed-package regressions; not model quality, GPU training or new-machine certification.')
        (output/'installed-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in evidence.items() if k != 'source_hashes'}, indent=2))
        os.chdir(output)
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())
