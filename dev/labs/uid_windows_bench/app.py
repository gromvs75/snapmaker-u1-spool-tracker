"""Standalone Tracker 2.0 isolated GUI; never opens installed Tracker data."""
import argparse
import json
from pathlib import Path
import sys
import traceback


def main():
    parser=argparse.ArgumentParser(description='Tracker 2.0 isolated GUI bench')
    parser.add_argument('--ci-self-test',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.ci_self_test:
        if not getattr(sys,'frozen',False):
            parser.error('CI executable check requires a frozen EXE')
        if args.output is None:
            parser.error('--output is required for CI')
        out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
        try:
            from dev.labs.uid_windows_bench.run import main as check
            check(out)
        except BaseException:
            (out/'launcher-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            return 1
        return 0
    from dev.labs.uid_gui_bench.run import main as launch
    sys.argv=[sys.argv[0],'--window','--resolution','--port','0']
    launch()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
