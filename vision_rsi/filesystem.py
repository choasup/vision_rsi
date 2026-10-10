"""Targeted native file-I/O paths; no system policy or registry changes."""
import os
from pathlib import Path


def native_path(value):
    """Use the Windows extended namespace for long absolute file-I/O paths."""
    path=Path(value)
    if os.name!='nt':return path
    text=os.fspath(path)
    prefix='\\\\?\\'
    if text.startswith(prefix):return path
    absolute=os.path.abspath(text)
    if len(absolute)<240:return path
    if absolute.startswith('\\\\'):
        return Path(prefix+'UNC\\'+absolute[2:])
    return Path(prefix+absolute)
