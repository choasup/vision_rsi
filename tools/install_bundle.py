"""Install a local Windows/Python 3.12 bundle offline; never reads credentials."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


def checksum(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def verify(root):
    manifest=json.loads((root/'bundle.json').read_text(encoding='utf-8'))
    if manifest.get('format')!='vision-rsi-offline-bundle-v1':raise ValueError('Unsupported bundle format')
    files=manifest['files']
    if not isinstance(files,dict) or not 1<=len(files)<=20:raise ValueError('Invalid bundle file list')
    for name,expected in files.items():
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z0-9_.+-]{1,200}',name) or name in ('.','..'):
            raise ValueError('Bundle paths must be plain filenames')
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('Invalid bundle checksum')
        path=root/name
        if path.is_symlink() or not path.is_file() or checksum(path)!=expected:
            raise ValueError('Bundle file missing or changed: '+name)
    if manifest['agent_wheel'] not in files or 'requirements.lock' not in files:raise ValueError('Incomplete bundle')
    return manifest


def main():
    root=Path(__file__).resolve().parent
    manifest=verify(root)  # Verify before creating any environment or running pip.
    if os.name!='nt' or sys.version_info[:2]!=(3,12) or platform.machine().lower() not in ('amd64','x86_64'):
        raise ValueError('This offline dependency bundle requires Windows x64 Python 3.12')
    target=root/'venv'
    if target.exists():raise ValueError('venv already exists; preserve it and install a fresh bundle directory')
    subprocess.run([sys.executable,'-m','venv',str(target)],check=True)
    python=target/'Scripts/python.exe'
    subprocess.run([str(python),'-m','pip','install','--no-index','--find-links',str(root),
                    '--require-hashes','-r',str(root/'requirements.lock')],check=True)
    subprocess.run([str(python),'-m','pip','install','--no-index','--no-deps',str(root/manifest['agent_wheel'])],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    version=subprocess.check_output([str(python),'-c',"import importlib.metadata;print(importlib.metadata.version('vision-rsi-agent'))"],text=True).strip()
    if version!=manifest['version']:raise ValueError('Installed package version mismatch')
    receipt={'installed_version':version,'wheel_sha256':manifest['files'][manifest['agent_wheel']],
             'source_revision':manifest['source_revision'],'offline':True,'remote_called':False,
             'quality_verified':False,'external_authenticity_verified':False}
    (root/'installation.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('Installed. Run vision-rsi.cmd --help. Configure task paths and API environment separately.')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        raise SystemExit(1)
