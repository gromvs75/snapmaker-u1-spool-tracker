"""Trusted offline endpoint for the experimental Snorca C++ bridge.

Only writes the explicitly named test report. Never creates a network transport.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from dev.presend_test_adapter import TestAdapter
from presend import decode_json, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'display', 'action', 'context', 'report'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    adapter = TestAdapter()
    result = {'decision': 'blocked', 'reason': 'Not checked'}
    try:
        config = decode_json(Path(args.context).read_bytes())
        if config.get('offline_test') is not True:
            raise ValueError('Explicit offline test context required')
        request = {'version': 1, 'request_id': str(uuid.uuid4()), 'context_id': str(uuid.uuid4()),
                   'device_id': config['device_id'], 'mapping': config['mapping'],
                   'action': args.action, 'gcode_path': args.source,
                   'inventory_path': config['inventory_path'],
                   'sha256': digest(Path(args.source).read_bytes())}
        result = adapter.execute(request, timeout=config.get('checker_timeout', 2),
                                 checker_command=config.get('checker_command'))
    except Exception as exc:
        result = {'decision': 'blocked', 'reason': str(exc)}
    report = {'mode': 'offline-only', 'action': args.action, 'display': args.display,
              'result': result, 'uploads': adapter.transport.uploads, 'starts': adapter.transport.starts}
    # A report write failure also prevents bridge success. No shell interpolation.
    Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    if result['decision'] == 'allowed':
        print('TRACKER_U1_OFFLINE_ALLOWED_V1')
        return 0
    return 23


if __name__ == '__main__':
    sys.exit(main())
