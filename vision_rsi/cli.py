"""Installed CLI and python -m share one entry point."""
import sys


def main():
    if len(sys.argv) > 2 and sys.argv[1] == 'training' and sys.argv[2] in ('--help','-h','start','reply','show','list','build','diagnose','define','validate','export','run'):
        from .training_cli import main as training_main
        training_main(sys.argv[2:])
    else:
        from .runner import main as legacy_main
        legacy_main()
