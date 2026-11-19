"""Verify a flat, unpacked RFID delivery without imports or network access."""
import hashlib
import json
from pathlib import Path


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Unsafe manifest path')
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing file or symlink: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Checksum mismatch: ' + name)
    return manifest


if __name__ == '__main__':
    try:
        result = verify(Path(__file__).resolve().parent)
        print('OK: RFID ' + result['module_version'] + '; Tracker ' + result['tracker_version'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit('FAILED: ' + str(exc))
