"""Offline recovery entry point, ONLY for the marked boot simulator."""
import argparse
import json
from pathlib import Path

from dev.labs.uid_boot_bench.model import BootModel, PersistenceTrial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'rollback', 'prepare-update'])
    parser.add_argument('--simulator-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        trial = PersistenceTrial(BootModel(args.simulator_root))
        result = (trial.inspect() if args.action == 'inspect' else
                  trial.rollback() if args.action == 'rollback' else trial.prepare_update())
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
