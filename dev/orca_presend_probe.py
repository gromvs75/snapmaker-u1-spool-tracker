#!/usr/bin/env python3
"""Temporary Orca post-processing probe: record invocation and reject output.

Use only in an isolated test preset. It never reads or modifies the G-code.
The nonzero exit is intentional; remove this script from the preset after testing.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

log = Path('/tmp/snapmaker-orca-presend-probe.jsonl')
entry = {
    'time_utc': datetime.now(timezone.utc).isoformat(),
    'argument_count': len(sys.argv) - 1,
    'gcode_argument_present': len(sys.argv) > 1,
    'host_type': os.environ.get('SLIC3R_PP_HOST'),
    'output_name_present': bool(os.environ.get('SLIC3R_PP_OUTPUT_NAME')),
}
with log.open('a', encoding='utf-8') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
print('TEST ONLY: Orca pre-send probe intentionally rejected this operation.', file=sys.stderr)
sys.exit(23)
