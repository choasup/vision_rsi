"""Installed CLI and python -m share one entry point."""
import sys


def main():
    if len(sys.argv)>1 and sys.argv[1]=='evaluate-events':
        from .event_eval import main as events_main
        return events_main(sys.argv[2:])
    if len(sys.argv)>1 and sys.argv[1]=='llm-usage':
        from .llm_usage import main as usage_main
        usage_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='resources-equivalence':
        from .resource_equivalence import main as equivalence_main
        equivalence_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='baseline-watch':
        from .baseline_watch import main as baseline_watch_main
        baseline_watch_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='baseline-status':
        from .baseline_observe import main as baseline_status_main
        baseline_status_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='baseline-audit':
        from .baseline_audit import main as audit_main
        audit_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='resources-train':
        from .training_resources import main as train_resources_main
        train_resources_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='baseline-evaluate':
        from .baseline_eval import main as baseline_main
        baseline_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='resources':
        from .resources_cli import main as resources_main
        resources_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='study':
        from .paired_study import main as study_main
        study_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='candidate':
        from .candidates import main as candidate_main
        candidate_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='coco-train':
        from .coco_train import main as train_main
        train_main(sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='evaluate-coco':
        from .coco_eval import main as evaluate_main
        evaluate_main(sys.argv[2:])
    elif len(sys.argv) > 2 and sys.argv[1] == 'training' and sys.argv[2] in ('--help','-h','start','reply','show','budget','accept','reject','recover','abandon-request','list','build','prepare','advance','watch','campaigns','memory','audit','readiness','agent-status','agent-pause','agent-resume','status','logs','cancel','collect','resume','register','serving-evaluate','runs','diagnose','define','validate','export','run'):
        from .training_cli import main as training_main
        training_main(sys.argv[2:])
    else:
        from .runner import main as legacy_main
        legacy_main()
