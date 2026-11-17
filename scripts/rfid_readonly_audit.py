"""Bounded, read-only U1 RFID audit. No install, service control or network calls.

Prints JSON to stdout. Never writes on the inspected filesystem. For a physical
U1, execute explicitly with --read-only-u1; --fixture-root is for local tests.
An inventory is diagnostic evidence, NOT a backup or permission to install.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time


UPPER = 'oem/overlay/upper'
PINNED_STOP_SCRIPT = '36a1bf014c3f21de5146c964c1f03dd3b245b1f3a0ae0d144d64e1eaddd1bccc'
FIXED_FILES = (
    'etc/init.d/S01aoverlayfs', 'etc/init.d/S48setup-lava-env',
    'etc/init.d/S60klipper', 'etc/init.d/S61moonraker', 'etc/init.d/S90lmd',
    'usr/sbin/cgroup_helper.sh', 'home/lava/bin/systemUpgrade.sh',
    'home/lava/klipper/klippy/extras/fm175xx_reader.py',
)
MARKERS = ('oem/.debug', 'oem/.printer_data', 'oem/printer_data/.fluidd',
           'oem/.factory', 'oem/.skip_checking_mcu')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_uid, info.st_gid, info.st_nlink)


def read_regular(path, limit):
    """Don't follow a final symlink or open FIFO/device; reject a changing file."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('not a regular file')
    if before.st_size > limit:
        raise ValueError('file size limit exceeded')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if identity(os.fstat(fd)) != identity(before):
            raise ValueError('file changed before read')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('file size limit exceeded')
        if identity(os.fstat(fd)) != identity(before) or identity(path.lstat()) != identity(before):
            raise ValueError('file changed during read')
        return raw
    finally:
        os.close(fd)


def metadata(info):
    mode = info.st_mode
    kind = ('file' if stat.S_ISREG(mode) else 'directory' if stat.S_ISDIR(mode) else
            'symlink' if stat.S_ISLNK(mode) else 'character' if stat.S_ISCHR(mode) else
            'block' if stat.S_ISBLK(mode) else 'fifo' if stat.S_ISFIFO(mode) else
            'socket' if stat.S_ISSOCK(mode) else 'unknown')
    value = dict(kind=kind, mode=stat.S_IMODE(mode), uid=info.st_uid, gid=info.st_gid,
                 size=info.st_size, mtime_ns=info.st_mtime_ns, links=info.st_nlink)
    if kind in ('character', 'block'):
        value['device'] = [os.major(info.st_rdev), os.minor(info.st_rdev)]
        value['possible_whiteout'] = kind == 'character' and info.st_rdev == 0
    return value


def inventory(root, *, max_entries=10000, max_file_bytes=2 * 1024**2,
              max_total_bytes=32 * 1024**2, max_seconds=15):
    """Walk through directory descriptors; never follow a link or open a device.

    Live metadata is not a coherent snapshot. Some trusted attributes may be hidden.
    """
    entries, errors = {}, []
    used = 0
    deadline = time.monotonic() + max_seconds
    root = Path(root)
    try:
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError('symlink in inventory root')
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (OSError, ValueError) as exc:
        return dict(entries={}, errors=[str(exc)], complete=False, hashed_bytes=0)
    device = os.fstat(root_fd).st_dev

    def visit(parent_fd, name, rel, depth):
        nonlocal used
        if len(entries) >= max_entries or time.monotonic() > deadline or depth > 64:
            raise ValueError('entry/time/depth limit reached; inventory incomplete')
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        entry = entries[rel] = metadata(info)
        if info.st_dev != device:
            raise ValueError('mount boundary; not traversed')
        if entry['kind'] == 'symlink':
            entry['target'] = os.readlink(name, dir_fd=parent_fd)
            entry['xattrs'] = None
            errors.append(rel + ': symlink xattrs not collected')
        elif entry['kind'] in ('directory', 'file'):
            if entry['kind'] == 'file' and info.st_nlink != 1:
                raise ValueError('hardlink requires review')
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if entry['kind'] == 'directory':
                flags |= os.O_DIRECTORY
            fd = os.open(name, flags, dir_fd=parent_fd)
            try:
                if identity(os.fstat(fd)) != identity(info):
                    raise ValueError('entry changed before open')
                try:
                    entry['xattrs'] = {key: digest(os.getxattr(fd, key)) for key in os.listxattr(fd)}
                except (OSError, AttributeError) as exc:
                    errors.append(rel + ': xattrs unreadable: ' + str(exc))
                if entry['kind'] == 'file':
                    limit = min(max_file_bytes, max_total_bytes - used)
                    if info.st_size > limit:
                        raise ValueError('file/total size limit exceeded')
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        raw = stream.read(limit + 1)
                    if len(raw) > limit:
                        raise ValueError('file/total size limit exceeded')
                    used += len(raw)
                    entry['sha256'] = digest(raw)
                else:
                    with os.scandir(fd) as children:
                        for child in children:
                            child_rel = child.name if rel == '.' else rel + '/' + child.name
                            try:
                                visit(fd, child.name, child_rel, depth + 1)
                            except (OSError, ValueError) as exc:
                                errors.append(child_rel + ': ' + str(exc))
                            if len(entries) >= max_entries or time.monotonic() > deadline:
                                raise ValueError('entry/time limit reached; inventory incomplete')
                if identity(os.fstat(fd)) != identity(info):
                    raise ValueError('entry changed during inventory')
            finally:
                os.close(fd)
        # All other types are recorded, never opened (including whiteouts/FIFOs).
        if identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != identity(info):
            raise ValueError('entry replaced during inventory')

    try:
        visit(root_fd, '.', '.', 0)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    finally:
        os.close(root_fd)
    return dict(entries=entries, errors=errors, complete=not errors, hashed_bytes=used,
                coherent_snapshot=False, trusted_xattrs_complete=False)


def process_snapshot(proc):
    """Only role/PID/start identity, never full command lines or environment."""
    rows, errors = [], []
    try:
        paths = [p for p in proc.iterdir() if p.name.isdecimal()]
    except OSError as exc:
        return dict(processes=[], errors=[str(exc)], complete=False)
    for p in paths[:4096]:
        try:
            args = read_regular(p / 'cmdline', 32768).split(b'\0')
            names = {a.rsplit(b'/', 1)[-1] for a in args if a}
            role = ('klipper' if b'klippy.py' in names else 'moonraker' if b'moonraker.py' in names
                    else 'lmd' if args and args[0].rsplit(b'/', 1)[-1] == b'lmd' else None)
            if not role:
                continue
            raw = read_regular(p / 'stat', 8192).decode()
            fields = raw[raw.rindex(')') + 2:].split()
            rows.append(dict(pid=int(p.name), role=role, state=fields[0],
                             start_ticks=int(fields[19])))
        except FileNotFoundError:
            errors.append(p.name + ': process disappeared during observation')
        except (OSError, ValueError, IndexError) as exc:
            errors.append(p.name + ': ' + str(exc))
    if len(paths) > 4096:
        errors.append('process limit exceeded')
    return dict(processes=rows, errors=errors, complete=not errors)


def service_observation(first, second, pidfile):
    """A matching PID is informational, not proof of exclusive service control."""
    def klipper(snapshot):
        return sorted((p['pid'], p['start_ticks']) for p in snapshot['processes'] if p['role'] == 'klipper')
    initial, final = klipper(first), klipper(second)
    try:
        pid = int(pidfile)
        if pid <= 0:
            raise ValueError('invalid PID')
    except (ValueError, TypeError):
        pid = None
    reasons = []
    if not first['complete'] or not second['complete']:
        reasons.append('process observation incomplete')
    if initial != final:
        reasons.append('Klipper process identity changed during observation')
    if len(final) > 1:
        reasons.append('multiple Klipper candidates')
    if pid is None or [p for p, _ in final] != [pid]:
        reasons.append('pidfile does not identify exactly one observed Klipper')
    return dict(pidfile_pid=pid, observed_klipper=final, warnings=reasons,
                stopped_proven=False, exclusive_control_proven=False)


def collect(root):
    root = Path(root).resolve(strict=True)
    files, markers = {}, {}
    for name in FIXED_FILES:
        try:
            # Refuse indirect paths for scripts/driver instead of trusting a link.
            path = root / name
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('symlink in inspected code path')
            raw = read_regular(path, 2 * 1024**2)
            files[name] = {'sha256': digest(raw)}
        except (OSError, ValueError) as exc:
            files[name] = {'error': str(exc)}
    for name in MARKERS:
        try:
            markers[name] = metadata((root / name).lstat())
        except FileNotFoundError:
            markers[name] = {'kind': 'absent'}
        except OSError as exc:
            markers[name] = {'error': str(exc)}
    text = {}
    for name in ('proc/self/mountinfo', 'proc/sys/kernel/random/boot_id', 'run/klipper.pid'):
        try:
            text[name] = read_regular(root / name, 128 * 1024).decode().strip()
        except (OSError, ValueError, UnicodeError) as exc:
            text[name] = {'error': str(exc)}
    observed_stop = files.get('etc/init.d/S60klipper', {}).get('sha256')
    first = process_snapshot(root / 'proc')
    time.sleep(.2)
    second = process_snapshot(root / 'proc')
    return dict(schema=1, mode='read-only-diagnostic', installation_allowed=False,
                files=files, markers=markers, system=text,
                overlay=inventory(root / UPPER), processes={'first': first, 'second': second},
                service=dict(pinned_stop_script_matches=observed_stop == PINNED_STOP_SCRIPT,
                             explicit_exit_wait_verified=False, supervisor_quiescence_verified=False,
                             hardware_restart_verified=False,
                             observation=service_observation(first, second, text['run/klipper.pid'])),
                limitations=['live non-atomic observation; not a backup',
                             'no proof that watchdog/lmd will not restart Klipper',
                             'trusted overlay xattrs may be hidden without privilege',
                             'does not execute vendor scripts or issue printer commands'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--read-only-u1', action='store_true')
    mode.add_argument('--fixture-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(collect(Path('/') if args.read_only_u1 else args.fixture_root),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
