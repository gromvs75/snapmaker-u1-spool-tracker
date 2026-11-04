"""Offline-only v1.2-alpha adapter. Its sole transport records in memory.

No HTTP, printer client, default inventory, or application imports. Not a Snorca
integration. Each instance permits only one attempt; retries need a fresh check.
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from presend import decode_json, digest, fingerprint, validate_request


class RecordingTransport:
    def __init__(self):
        self.uploads = []
        self.starts = []

    def upload(self, data, device_id):
        self.uploads.append({'sha256': digest(data), 'device_id': device_id})

    def start(self, device_id):
        self.starts.append(device_id)


class TestAdapter:
    __test__ = False

    def __init__(self):
        self.transport = RecordingTransport()
        self.attempted = False

    def execute(self, request, *, timeout=5, checker_command=None):
        if self.attempted:
            return {'decision': 'blocked', 'reason': 'Attempt already consumed'}
        self.attempted = True
        try:
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError('Invalid timeout')
            # Detach nested mapping from caller-owned mutable input.
            original = decode_json(json.dumps(request, allow_nan=False))
            validate_request(original)
            data = Path(original['gcode_path']).read_bytes()
            inventory = Path(original['inventory_path']).read_bytes()
            if digest(data) != original['sha256']:
                raise ValueError('G-code changed before check')
            with tempfile.TemporaryDirectory(prefix='tracker-presend-') as folder:
                root = Path(folder)
                (root / 'job.gcode').write_bytes(data)
                (root / 'inventory.json').write_bytes(inventory)
                snapshot = dict(original, gcode_path=str(root / 'job.gcode'),
                                inventory_path=str(root / 'inventory.json'))
                request_path = root / 'request.json'
                request_path.write_text(json.dumps(snapshot), encoding='utf-8')
                command = checker_command if checker_command is not None else [
                    sys.executable, str(Path(__file__).resolve().parents[1] / 'src' / 'presend.py')]
                if not isinstance(command, (list, tuple)) or not command:
                    raise ValueError('Checker must be an argument list')
                completed = subprocess.run([*command, '--request', str(request_path)],
                                           capture_output=True, timeout=timeout, check=False)
                if completed.returncode != 0:
                    raise ValueError('Checker failed or denied: ' + str(completed.returncode))
                response = decode_json(completed.stdout)
                if (not isinstance(response, dict) or type(response.get('version')) is not int
                        or response['version'] != 1 or response.get('decision') != 'allow'
                        or response.get('request_fingerprint') != fingerprint(snapshot)
                        or response.get('sha256') != digest(data)
                        or response.get('inventory_sha256') != digest(inventory)):
                    raise ValueError('Invalid or unrelated permission')
                if (fingerprint(request) != fingerprint(original)
                        or Path(original['gcode_path']).read_bytes() != data
                        or Path(original['inventory_path']).read_bytes() != inventory):
                    raise ValueError('Inputs changed during check')
                # Upload the checked immutable bytes, never reopen a mutable path.
                self.transport.upload(data, original['device_id'])
                if original['action'] == 'print':
                    self.transport.start(original['device_id'])
                return {'decision': 'allowed', 'response': response}
        except Exception as exc:
            return {'decision': 'blocked', 'reason': str(exc)}
