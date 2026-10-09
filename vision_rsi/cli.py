"""Installed CLI and python -m share one entry point."""
import sys


def main():
    if len(sys.argv)>1 and sys.argv[1]=='coco-train':
        from .coco_train import main as train_main
        train_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='evaluate-coco':
        from .coco_eval import main as evaluate_main
        evaluate_main(sys.argv[2:])
    elif len(sys.argv) > 2 and sys.argv[1] == 'training' and sys.argv[2] in ('--help','-h','start','reply','show','list','build','prepare','status','logs','cancel','collect','runs','diagnose','define','validate','export','run'):
        from .training_cli import main as training_main
        training_main(sys.argv[2:])
    else:
        from .runner import main as legacy_main
        legacy_main()
