"""Windows launcher without requiring PowerShell script execution permission."""
import argparse
import json
import os
import sys
import runpy
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError


def task_cli_paths(arguments,caller):
    """Explicit local task paths belong to the caller; defaults belong to the app."""
    if not arguments:return []
    if arguments[0]=='workspace-init' and not any(arg.partition('=')[0]=='--directory' for arg in arguments[1:]):
        return list(arguments)+['--directory',str(caller.resolve())]
    task_paths={'--config','--sessions','--run-store','--campaign-store','--registry','--candidate-store','--research-root','--repository',
           '--contract','--sample','--result','--output','--manifest','--input','--input-dir','--output-dir','--task','--bundle'}
    paths={'training':task_paths,'test':task_paths,
           'candidate':task_paths|{'--store','--proposal','--evidence','--cases','--report','--dataset'},
           'candidate-run':{'--bundle','--input','--output','--config'},
           'candidate-evaluate':{'--bundle','--dataset','--output','--config'},
            'input-overlap':{'--development','--acceptance'},
           'workspace-init':{'--directory'},
           'evaluate-events':{'--ground-truth','--predictions','--contract','--output'},
           'experiment-request':{'--store'}}.get(arguments[0])
    if paths is None:return list(arguments)
    result=[];index=0
    while index<len(arguments):
        argument=arguments[index];flag,separator,value=argument.partition('=')
        if flag in paths:
            if separator:
                result.append(flag+'='+str((caller/value).resolve()) if value else argument)
            elif index+1<len(arguments) and arguments[index+1] and not arguments[index+1].startswith('-'):
                result.extend([flag,str((caller/arguments[index+1]).resolve())]);index+=1
            else:result.append(argument)  # Let argparse report missing values.
        else:result.append(argument)
        index+=1
    return result


def main():
    caller=Path.cwd()
    os.chdir(Path(__file__).resolve().parent)
    if len(sys.argv) > 1 and sys.argv[1] == '--cli':
        if os.name == 'nt' and not os.environ.get('DEEPSEEK_API_KEY'):
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
                    value, _ = winreg.QueryValueEx(registry, 'DEEPSEEK_API_KEY')
                    if isinstance(value, str): os.environ['DEEPSEEK_API_KEY'] = value
            except OSError:
                pass
        sys.argv = ['vision-rsi'] + task_cli_paths(sys.argv[2:],caller)
        runpy.run_module('vision_rsi', run_name='__main__')
        return
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Validate launch setup without starting a server')
    args = parser.parse_args()
    path = Path('config.local.json')
    if not path.exists():
        raise SystemExit('Missing config.local.json; copy config.example.json and configure it first.')
    config = json.loads(path.read_text(encoding='utf-8'))
    key_env = config['llm']['api_key_env']
    if not os.environ.get(key_env) and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
                value, _ = winreg.QueryValueEx(registry, key_env)
                if isinstance(value, str) and value:
                    os.environ[key_env] = value
        except OSError:
            pass
    if not os.environ.get(key_env):
        raise SystemExit('Missing API key environment variable: ' + key_env)
    if args.check:
        print('Launch configuration OK; API key present (value hidden).')
        return
    address = 'http://127.0.0.1:8767/'
    try:
        with urlopen(address, timeout=2) as response:
            existing = response.read(20000).decode(errors='replace')
        if '<title>Vision RSI Agent</title>' in existing:
            print('Agent is already running: ' + address)
            return
        raise SystemExit('Port 8767 is occupied by another application.')
    except (URLError, TimeoutError):
        pass
    from vision_rsi.app import serve
    serve(config, 'runs/app', str(Path.cwd()), 8767)


if __name__ == '__main__':
    main()
