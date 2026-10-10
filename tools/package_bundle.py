"""Assemble a local offline bundle from a built wheel and hash-locked wheels."""
import argparse
import email
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from install_bundle import checksum


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',required=True)
    parser.add_argument('--dependency-wheelhouse',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip():
        raise ValueError('Commit source changes before assembling a bundle')
    wheel=Path(args.wheel).resolve();target=Path(args.output).resolve()
    if target.exists():raise ValueError('Bundle output already exists; never overwrite an installation')
    lock=repo/'requirements-control-windows-py312.lock'
    hashes=re.findall(r'--hash=sha256:([0-9a-f]{64})',lock.read_text(encoding='utf-8'))
    dependencies={checksum(path):path for path in Path(args.dependency_wheelhouse).glob('*.whl')}
    if not hashes or any(value not in dependencies for value in hashes):raise ValueError('Missing hash-locked dependency wheels')
    with zipfile.ZipFile(wheel) as archive:
        names=[name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        if len(names)!=1:raise ValueError('Invalid agent wheel metadata')
        metadata=email.message_from_bytes(archive.read(names[0]))
    if metadata['Name']!='vision-rsi-agent':raise ValueError('Unexpected agent package')
    target.mkdir(parents=True)
    for path in [wheel]+[dependencies[value] for value in hashes]:shutil.copy2(path,target/path.name)
    shutil.copy2(lock,target/'requirements.lock')
    shutil.copy2(repo/'tools/install_bundle.py',target/'install.py')
    (target/'vision-rsi.cmd').write_bytes(b'@echo off\r\n"%~dp0venv\\Scripts\\python.exe" -X utf8 -m vision_rsi %*\r\nexit /b %errorlevel%\r\n')
    manifest={'format':'vision-rsi-offline-bundle-v1','version':metadata['Version'],'agent_wheel':wheel.name,
              'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
              'files':{path.name:checksum(path) for path in sorted(target.iterdir())}}
    (target/'bundle.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(str(target))


if __name__=='__main__':main()
