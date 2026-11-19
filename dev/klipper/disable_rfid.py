"""Independent, stdlib-only OFF switch for the marked RFID filesystem bench.

No imports from Tracker, Klipper, Moonraker, the module or its loader. No network
or service control. Disables future loads; it cannot unload code already running.
Never create the simulator marker on a real printer to bypass this lab boundary.
"""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

MARKER = {'kind': 'tracker-uid-filesystem-simulator', 'version': 1}
DEPLOY = 'persistent/tracker-deployment'
CFG = 'klipper/klippy/extras/tracker_uid_boot.cfg'
ENABLED = DEPLOY + '/selective-enabled'


def path_in(root, name):
    path = root
    for part in Path(name).parts:
        if part in ('..', '/'):
            raise ValueError('Unsafe recovery path')
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink recovery path')
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise ValueError('Special recovery path')
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError('Hardlinked recovery file')
    return path


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable(path, content):
    fd, temp = tempfile.mkstemp(prefix='.rfid-off-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def disable(root, *, fail_after=None):
    import fcntl  # POSIX operation; keep import/Windows test collection portable.
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Use a canonical simulator path')
    root = root.resolve(strict=True)
    if json.loads(path_in(root, '.tracker-uid-simulator.json').read_text()) != MARKER:
        raise ValueError('Only marked simulators are supported')
    # Same order as the boot loader. An active/error Klippy process is allowed:
    # this changes next-start configuration, never its memory or service state.
    with contextlib.ExitStack() as stack:
        for name in (DEPLOY + '/debug-loader.lock', '.tracker-uid-install.lock'):
            lock = stack.enter_context(path_in(root, name).open('a+b'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = json.loads(path_in(root, DEPLOY + '/optional-plan.json').read_text())
        revision = record.pop('revision')
        raw = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        pattern = path_in(root, CFG).with_name('[t]racker_uid_boot.cfg')
        block = ('\n# BEGIN TRACKER UID OPTIONAL BOOT\n[include ' + str(pattern)
                 + ']\n# END TRACKER UID OPTIONAL BOOT\n').encode()
        if (record.get('schema') != 1 or record.get('root') != str(root)
                or hashlib.sha256(raw).hexdigest() != revision
                or base64.b64decode(record['block'], validate=True) != block):
            raise ValueError('Invalid installation ownership record')
        main = path_in(root, 'printer_data/config/printer.cfg')
        if main.read_bytes().count(block) != 1:
            raise ValueError('Activation include changed; inspect configuration')
        enabled, cfg = path_in(root, ENABLED), path_in(root, CFG)
        archive = path_in(root, DEPLOY + '/disabled-configs')
        archive.mkdir(mode=0o700, exist_ok=True)
        # Withdraw future activation first. No module validation/import is needed,
        # so syntax errors, absent modules and invalid options cannot block OFF.
        enabled.unlink(missing_ok=True)
        sync_dir(enabled.parent)
        if fail_after == 0:
            raise RuntimeError('Interrupted after future activation disabled')
        retained = None
        if cfg.exists():
            retained = archive / (uuid.uuid4().hex + '.cfg.disabled')
            os.replace(cfg, retained)
            sync_dir(archive)
            sync_dir(cfg.parent)
        if fail_after == 1:
            raise RuntimeError('Interrupted after activating config withdrawn')
        result = dict(state='disabled', effective='next-klipper-start',
                      saved_config=str(retained.relative_to(root)) if retained else None,
                      module_left_for_diagnosis=True, services_changed=False,
                      physical_installation=False)
        durable(path_in(root, DEPLOY + '/emergency-off.json'),
                json.dumps(result, indent=2).encode())
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(disable(args.simulator_root)))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(state='review-required', error=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
