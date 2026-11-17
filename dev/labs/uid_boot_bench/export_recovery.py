"""Export an independent, stdlib-only SIMULATOR recovery kit, not a U1 installer."""
import argparse
import json
from pathlib import Path
import shutil

from scripts import rfid_module_tool as tool


BOOTSTRAP = '''"""Offline simulator recovery. No SSH, service control or printer deployment."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
expected = {'scripts/rfid_module_tool.py', 'scripts/tracker_uid.py',
            'dev/labs/uid_boot_bench/model.py', 'dev/labs/uid_boot_bench/recovery.py'}
try:
    manifest = json.loads((root / 'recovery-manifest.json').read_text())
    if manifest.get('schema') != 1 or set(manifest.get('files', {})) != expected:
        raise ValueError('Invalid recovery manifest')
    for name, digest in manifest['files'].items():
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink in recovery bundle')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Recovery integrity failure: ' + name)
except (OSError, ValueError, TypeError) as exc:
    print(json.dumps({'error': str(exc)}))
    raise SystemExit(1)
sys.path.insert(0, str(root))
from dev.labs.uid_boot_bench.recovery import main
raise SystemExit(main())
'''


def export(destination):
    repo = Path(__file__).resolve().parents[3]
    destination = Path(destination)
    # Never overwrite an earlier recovery package.
    destination.mkdir(parents=True, exist_ok=False)
    sources = {
        'scripts/rfid_module_tool.py': repo / 'scripts/rfid_module_tool.py',
        'scripts/tracker_uid.py': repo / 'dev/klipper/tracker_uid.py',
        'dev/labs/uid_boot_bench/model.py': Path(__file__).with_name('model.py'),
        'dev/labs/uid_boot_bench/recovery.py': Path(__file__).with_name('recovery.py'),
    }
    hashes = {}
    for name, source in sources.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = tool.sha(target.read_bytes())
    (destination / 'recovery-manifest.json').write_bytes(tool.canonical({'schema': 1, 'files': hashes}))
    (destination / 'recover.py').write_text(BOOTSTRAP)
    (destination / 'README.txt').write_text(
        'SIMULATOR ONLY. Do not copy to a printer or create simulator markers on U1.\n'
        'Python 3, standard library, POSIX. No desktop app/database/checkout needed.\n'
        'python3 -I recover.py inspect --simulator-root /absolute/marked/bench\n'
        'Actions: inspect, rollback, prepare-update. No automatic installation.\n'
        'Keep persistent/tracker-deployment and _boot_lower with the bench.\n'
        'Firmware change or foreign system edits require review; never force rollback.\n'
        'Checksums detect accidental corruption, not a malicious replacement of this kit.\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(export(parser.parse_args().output))
