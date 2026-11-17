"""Offline RFID deployment rehearsal. Writes ONLY to marked, stopped simulators.

No SSH, printer requests, service control, firmware flashing or driver writes.
The marker is a bench convention, not evidence that a real printer is stopped.
Do not manufacture it on a real printer to bypass this restriction.
"""
import argparse
import ast
import base64
import contextlib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

MARKER = {'kind': 'tracker-uid-filesystem-simulator', 'version': 1}
BLOCK = b'\n# BEGIN TRACKER UID\n[include tracker_uid.cfg]\n# END TRACKER UID\n'
CONFIG = b'[tracker_uid]\nenabled: True\nstale_after: 300\n'
MODULE = Path(__file__).with_name('tracker_uid.py')
if not MODULE.exists():
    MODULE = Path(__file__).resolve().parents[1] / 'dev/klipper/tracker_uid.py'
DRIVER = 'klipper/klippy/extras/fm175xx_reader.py'
MAIN = 'printer_data/config/printer.cfg'
TARGETS = ('klipper/klippy/extras/tracker_uid.py', 'printer_data/config/tracker_uid.cfg', MAIN)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return base64.b64encode(value).decode()


def decode(value):
    return base64.b64decode(value, validate=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def atomic(path, content, mode=0o644):
    fd, temporary = tempfile.mkstemp(prefix='.tracker-stage-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content); f.flush(); os.fsync(f.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def supported_drivers():
    # Read the allowlist without executing either the module or printer code.
    tree = ast.parse(MODULE.read_bytes())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == 'SUPPORTED_DRIVERS' for t in n.targets))
    return ast.literal_eval(node.value)


def verify_bundle():
    manifest = Path(__file__).with_name('manifest.json')
    if not manifest.exists(): return  # Repository checkout, rather than exported kit.
    value = json.loads(manifest.read_text())
    expected = {'rfid_module_tool.py', 'tracker_uid.py', 'README-RU.md', 'README-EN.md'}
    if value.get('schema') != 1 or set(value.get('files', {})) != expected:
        raise ValueError('Invalid kit manifest')
    for name, digest in value['files'].items():
        path = manifest.parent / name
        if path.is_symlink() or sha(path.read_bytes()) != digest:
            raise ValueError('Kit integrity check failed: ' + name)


class Installer:
    def __init__(self, root):
        verify_bundle()
        root = Path(root).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            # macOS /tmp itself is a symlink: callers should pass /private/tmp.
            raise ValueError('Symlink root forbidden; use a canonical simulator path')
        self.root = root.resolve(strict=True)
        marker = self.path('.tracker-uid-simulator.json')
        if json.loads(marker.read_text()) != MARKER:
            raise ValueError('Only a marked simulator root is allowed')
        self.journal = self.path('.tracker-uid-journal.json')
        self.lock_path = self.path('.tracker-uid-install.lock')

    def path(self, name):
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe path')
        p = self.root
        for part in rel.parts:
            p = p / part
            if p.is_symlink(): raise ValueError('Symlink destination forbidden')
        if p.exists() and not (p.is_file() or p.is_dir()):
            raise ValueError('Special file forbidden')
        if p.is_file() and p.stat().st_nlink != 1:
            raise ValueError('Hardlinked file forbidden')
        return p

    @contextlib.contextmanager
    def locked(self):
        import fcntl  # POSIX-only deployment rehearsal, not the Windows GUI.
        with self.path('.tracker-uid-install.lock').open('a+b') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path('.klipper-running').exists():
                raise ValueError('Stop simulated Klipper first')
            yield

    def current(self, name):
        path = self.path(name)
        return path.read_bytes() if path.exists() else None

    def configs(self):
        """Resolve includes under config root; reject cycles and duplicate module loads."""
        found = {}
        cfgroot = self.path('printer_data/config')
        def visit(relative, stack):
            if relative in stack: raise ValueError('Config include cycle')
            path = self.path(relative)
            raw = path.read_bytes()
            found[relative] = sha(raw)
            for line in raw.decode('utf-8').splitlines():
                line = re.split(r'[;#]', line, 1)[0].strip()
                if re.fullmatch(r'\[tracker_uid\]', line, re.I):
                    raise ValueError('Existing tracker_uid configuration in ' + relative)
                match = re.fullmatch(r'\[include\s+(.+?)\]', line, re.I)
                if not match: continue
                pattern = match[1].strip()
                if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                    raise ValueError('Include outside supported config layout')
                # If our new cfg would match a wildcard, adding an explicit include
                # would load it twice. Refuse; never rewrite the user's include graph.
                candidate = self.path(TARGETS[1])
                try: name = candidate.relative_to(path.parent).as_posix()
                except ValueError: name = None
                if name is not None and fnmatch.fnmatchcase(name, pattern):
                    raise ValueError('Existing include would load tracker_uid.cfg')
                matches = sorted(path.parent.glob(pattern))
                if not matches and not any(c in pattern for c in '*?['):
                    raise ValueError('Missing included config: ' + pattern)
                for child in matches:
                    child.relative_to(cfgroot)  # All reads stay inside the known tree.
                    visit(child.relative_to(self.root).as_posix(), stack + [relative])
        visit(MAIN, [])
        return found

    def plan(self):
        if self.journal.exists(): raise ValueError('Existing transaction; inspect or rollback first')
        digest = sha(self.path(DRIVER).read_bytes())
        version = supported_drivers().get(digest)
        if not version: raise ValueError('Unsupported driver hash')
        configs = self.configs()
        changes = []
        for name, new in zip(TARGETS, (MODULE.read_bytes(), CONFIG, self.path(MAIN).read_bytes() + BLOCK)):
            path = self.path(name); old = self.current(name)
            if name != MAIN and old is not None: raise ValueError('Destination already exists')
            changes.append(dict(path=name, old=encode(old) if old is not None else None,
                                new=encode(new), old_sha256=sha(old) if old is not None else None,
                                new_sha256=sha(new), mode=stat.S_IMODE(path.stat().st_mode) if old is not None else 0o644))
        value = dict(schema=2, root=str(self.root), driver_sha256=digest, driver_version=version,
                     module_sha256=sha(MODULE.read_bytes()), configs=configs, files=changes)
        return dict(value, revision=sha(canonical(value)))

    def inspect(self):
        try:
            if self.journal.exists():
                journal = self.read_journal()
                return dict(compatible=sha(self.path(DRIVER).read_bytes()) == journal['driver_sha256']
                            and journal['driver_sha256'] in supported_drivers()
                            and sha(MODULE.read_bytes()) == journal['module_sha256'],
                            state=journal['state'], driver_version=journal['driver_version'],
                            driver_sha256=sha(self.path(DRIVER).read_bytes()),
                            files_match=all(self.current(i['path']) == decode(i['new']) for i in journal['files']))
            plan = self.plan()
            return dict(compatible=True, state='not-installed', driver_version=plan['driver_version'],
                        driver_sha256=plan['driver_sha256'], plan_revision=plan['revision'],
                        changes=[dict(path=i['path'], old_sha256=i['old_sha256'], new_sha256=i['new_sha256']) for i in plan['files']])
        except (ValueError, OSError, KeyError) as exc:
            return dict(compatible=False, state='blocked', reason=str(exc))

    def read_journal(self):
        value = json.loads(self.path('.tracker-uid-journal.json').read_text())
        if value.get('schema') != 2 or value.get('state') not in ('pending', 'installed', 'rolling-back'):
            raise ValueError('Invalid journal; preserve backup for manual inspection')
        backup = value.get('backup', '')
        if not re.fullmatch(r'\.tracker-uid-backups/[0-9a-f]{32}\.json', backup):
            raise ValueError('Invalid backup path')
        raw = self.path(backup).read_bytes()
        if sha(raw) != value.get('backup_sha256'): raise ValueError('Backup integrity check failed')
        plan = json.loads(raw)
        if plan.get('root') != str(self.root) or plan.get('schema') != 2:
            raise ValueError('Backup belongs to another root')
        revision = plan.pop('revision')
        if sha(canonical(plan)) != revision: raise ValueError('Invalid backup plan')
        plan['revision'] = revision
        if any(value.get(k) != v for k, v in plan.items()):
            raise ValueError('Journal differs from immutable backup')
        if [i['path'] for i in plan['files']] != list(TARGETS): raise ValueError('Invalid journal targets')
        for item in plan['files']:
            self.path(item['path'])
            if sha(decode(item['new'])) != item['new_sha256'] or (
                sha(decode(item['old'])) if item['old'] is not None else None) != item['old_sha256']:
                raise ValueError('Invalid backup content')
        return value

    def save_journal(self, value):
        atomic(self.path('.tracker-uid-journal.json'), canonical(value), 0o600)

    def install(self, fail_after=None, expected_revision=None):
        with self.locked():
            if self.journal.exists():
                old = self.read_journal()
                if old['state'] != 'installed': raise ValueError('Pending transaction: rollback first')
                if sha(self.path(DRIVER).read_bytes()) != old['driver_sha256']:
                    raise ValueError('Driver changed since installation')
                if sha(MODULE.read_bytes()) != old['module_sha256']: raise ValueError('Different module build')
                if any(self.current(i['path']) != decode(i['new']) for i in old['files']):
                    raise ValueError('Installed files changed; inspect before updating')
                return 'already-installed'
            plan = self.plan()
            if expected_revision is not None and expected_revision != plan['revision']:
                raise ValueError('Stale plan; inspect and prepare again')
            backup_dir = self.path('.tracker-uid-backups')
            backup_dir.mkdir(mode=0o700, exist_ok=True)
            backup = '.tracker-uid-backups/' + uuid.uuid4().hex + '.json'
            raw = canonical(plan)
            atomic(self.path(backup), raw, 0o600)
            journal = dict(plan, state='pending', backup=backup, backup_sha256=sha(raw))
            self.save_journal(journal)
            for n, item in enumerate(plan['files'], 1):
                expected = decode(item['old']) if item['old'] is not None else None
                if self.current(item['path']) != expected:
                    raise ValueError('Concurrent change; rollback pending transaction')
                if self.configs() != plan['configs']:
                    raise ValueError('Concurrent config change; rollback pending transaction')
                if sha(self.path(DRIVER).read_bytes()) != plan['driver_sha256']:
                    raise ValueError('Concurrent driver change; rollback pending transaction')
                atomic(self.path(item['path']), decode(item['new']), item['mode'])
                if fail_after == n: raise RuntimeError('Simulated installation interruption')
            journal['state'] = 'installed'; self.save_journal(journal)
            return 'installed'

    def rollback(self, fail_after=None):
        with self.locked():
            if not self.journal.exists(): return 'not-installed'
            journal = self.read_journal()
            if journal['state'] != 'rolling-back':
                actions = []
                for item in journal['files']:
                    current = self.current(item['path'])
                    old = decode(item['old']) if item['old'] is not None else None
                    new = decode(item['new'])
                    if current == old: restored = old
                    elif current == new: restored = old
                    elif item['path'] == MAIN and current is not None and current.count(BLOCK) == 1:
                        restored = current.replace(BLOCK, b'', 1)
                    else: raise ValueError('Owned file changed; refusing destructive rollback')
                    actions.append(dict(path=item['path'], before=encode(current) if current is not None else None,
                                        after=encode(restored) if restored is not None else None, mode=item['mode']))
                journal.update(state='rolling-back', rollback=actions)
                journal['rollback_sha256'] = sha(canonical(actions))
                self.save_journal(journal)
            actions = journal.get('rollback', [])
            if sha(canonical(actions)) != journal.get('rollback_sha256') or [i['path'] for i in actions] != list(TARGETS):
                raise ValueError('Invalid rollback journal')
            # Validate the whole set before a single write, including resumed rollback.
            for item in actions:
                before = decode(item['before']) if item['before'] is not None else None
                after = decode(item['after']) if item['after'] is not None else None
                if self.current(item['path']) not in (before, after):
                    raise ValueError('Concurrent edit during rollback; no overwrite')
            for n, item in enumerate(reversed(actions), 1):
                dest = self.path(item['path'])
                after = decode(item['after']) if item['after'] is not None else None
                before = decode(item['before']) if item['before'] is not None else None
                current = self.current(item['path'])
                if current not in (before, after): raise ValueError('Concurrent edit during rollback')
                if current != after:
                    if after is None: dest.unlink(); sync_dir(dest.parent)
                    else: atomic(dest, after, item['mode'])
                if fail_after == n: raise RuntimeError('Simulated rollback interruption')
            atomic(self.path('.tracker-uid-last-rollback.json'), canonical(journal), 0o600)
            self.journal.unlink(); sync_dir(self.root)
            return 'rolled-back'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'plan', 'install', 'rollback'])
    parser.add_argument('--simulator-root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, help='Reviewed JSON plan required by install')
    args = parser.parse_args()
    try:
        installer = Installer(args.simulator_root)
        if args.action == 'inspect': result = installer.inspect()
        elif args.action == 'plan': result = installer.plan()
        elif args.action == 'install':
            if not args.plan: raise ValueError('install requires --plan from the plan command')
            saved = json.loads(args.plan.read_text())
            # Compare the complete plan, not only a user-editable revision field.
            if installer.journal.exists():
                old = installer.read_journal()
                if any(old.get(k) != v for k, v in saved.items()): raise ValueError('Plan differs from installed transaction')
            elif saved != installer.plan(): raise ValueError('Stale or modified plan')
            result = installer.install(expected_revision=saved['revision'])
        else: result = installer.rollback()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if isinstance(result, dict) and result.get('compatible') is False else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
