"""One-command local dashboard startup with explicit workspace discovery."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shlex
import webbrowser

from .workspace import initialize


def configuration(directory, explicit=None):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise ValueError('找不到指定配置文件：' + str(path))
    else:
        candidates = [p for p in (root/'config.local.json', root/'works/config.local.json') if p.is_file()]
        if len(candidates) > 1:
            raise ValueError('发现两份配置，请用 --config 指定要使用的一份；原文件均已保留。')
        if candidates:
            path = candidates[0]
        else:
            path = Path(initialize(root)['config'])
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as error:
        raise ValueError('配置文件无法读取，请检查 JSON 格式：' + str(path)) from error
    if not isinstance(config, dict) or not isinstance(config.get('llm', {}), dict):
        raise ValueError('配置文件应包含 JSON 对象，llm 也必须为对象。')
    return root, path, config


def access_instructions(port, environ=None):
    environ = os.environ if environ is None else environ
    address = 'http://127.0.0.1:' + str(port)
    if environ.get('SSH_CONNECTION'):
        parts = environ['SSH_CONNECTION'].split()
        if len(parts) == 4 and parts[3].isdigit():
            target = getpass.getuser() + '@' + parts[2]
            command = 'ssh -N -L '+str(port)+':127.0.0.1:'+str(port)+' -p '+parts[3]+' '+shlex.quote(target)
            return '服务已在服务器启动。请在你电脑上执行：\n  '+command+'\nSSH 地址取自当前连接；若使用公网地址或跳板机，请换成你平时登录的地址。\n保持转发窗口打开，再在电脑浏览器输入：'+address
        return '服务已在远端启动。请通过 SSH 转发 '+str(port)+' 端口后，在电脑浏览器输入：'+address
    return '本机浏览器地址：'+address+'\n若通过云平台终端操作，请使用平台端口转发，或 SSH 转发此端口后访问。'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='vision-rsi dashboard', description='一条命令打开实验工作台；自动检查配置、能力和端口。')
    parser.add_argument('--directory', default='.', help='工作目录，默认当前目录')
    parser.add_argument('--config', help='可选：指定已有配置')
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--check', action='store_true', help='检查配置和能力后退出')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在 1..65535 内')
    try:
        root, path, config = configuration(args.directory, args.config)
        from .console import make_server, capabilities
        checks = capabilities(config)
        print('工作目录：'+str(root)+'\n配置文件：'+str(path), flush=True)
        for item in checks['checks']:
            print(('✓ ' if item['ready'] else '· ')+item['message'], flush=True)
        if args.check:
            return
        from .campaign import lease
        state = root/'runs/dashboard'
        state.mkdir(parents=True, exist_ok=True)
        with lease(state/'console.lock', owner='Dashboard single writer'):
            server = None
            for port in range(args.port, min(args.port+10, 65536)):
                try:
                    server = make_server(state, config, port, sessions_root=root/'runs/training-sessions',
                                         harness_root=root/'runs/task-harnesses')
                    break
                except OSError as error:
                    import errno
                    if error.errno != errno.EADDRINUSE:
                        raise
            if server is None:
                raise ValueError('可选端口均被占用，请用 --port 指定其他端口。')
            print(access_instructions(port), flush=True)
            print('先点击“体验一次实验”，无需填写模型凭据。退出工作台服务请按 Ctrl+C。', flush=True)
            if not args.no_browser and not os.environ.get('SSH_CONNECTION') and (os.name=='nt' or os.environ.get('DISPLAY') or __import__('sys').platform=='darwin'):
                webbrowser.open('http://127.0.0.1:'+str(port))
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, '工作台暂未启动：'+str(error)+'\n已有任务已保留；解决上述问题后重新运行同一命令。\n')


if __name__ == '__main__':
    main()
