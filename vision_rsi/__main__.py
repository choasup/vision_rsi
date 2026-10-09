import sys

if len(sys.argv) > 2 and sys.argv[1] == 'training' and sys.argv[2] in ('--help','-h','start','reply','show','list','define','validate','export','run'):
    from .training_cli import main
    main(sys.argv[2:])
else:
    from .runner import main
    main()
