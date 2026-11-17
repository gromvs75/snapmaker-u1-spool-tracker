"""Materialized filesystem model of U1 boot policy; never runs vendor scripts.

This is a laboratory experiment, NOT a printer deployment tool. All writes are
inside an already marked simulator. No mounts, SSH, MCU control or firmware
commands. `klipper/` represents the merged system tree; `printer_data/` and
`persistent/` represent OEM data outside the volatile overlay. Kernel overlayfs
atomicity, physical power loss and vendor firmware update internals are not modeled.
"""
import json
import os
from pathlib import Path
import shutil
import stat

from scripts import rfid_module_tool as tool

BOOT_MARKER = {'kind': 'u1-materialized-boot-model', 'version': 1}


def inventory(path, *, exclude_uid=False):
    """Inventory a materialized tree without following symlinks.

    Deletions are represented by missing entries, not real OverlayFS whiteouts.
    Special files/hardlinks are deliberately unsupported, never silently skipped.
    """
    result = {}

    def visit(p, rel):
        info = p.lstat()
        item = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISLNK(info.st_mode):
            item.update(kind='symlink', target=os.readlink(p))
        elif stat.S_ISDIR(info.st_mode):
            item['kind'] = 'directory'
            for child in sorted(p.iterdir()):
                name = '/'.join(filter(None, (rel, child.name)))
                if exclude_uid and (name == 'klippy/extras/tracker_uid.py' or
                                    child.name == '__pycache__' or child.suffix == '.pyc'):
                    continue
                visit(child, name)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            item.update(kind='file', sha256=tool.sha(p.read_bytes()))
        else:
            raise ValueError('Unsupported special or hardlinked system entry: ' + rel)
        result[rel or '.'] = item

    visit(path, '')
    return result


def differences(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)}
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)}


def tree(path):
    """Fingerprint system source/files, excluding ordinary Python cache output."""
    result = {}
    for p in sorted(path.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symlink in modeled system tree')
        if not p.is_file() or '__pycache__' in p.parts or p.suffix == '.pyc':
            continue
        if p.relative_to(path).as_posix() == 'klippy/extras/tracker_uid.py':
            continue
        result[p.relative_to(path).as_posix()] = {
            'sha256': tool.sha(p.read_bytes()), 'mode': stat.S_IMODE(p.stat().st_mode)}
    return result


class BootModel:
    def __init__(self, root):
        self.base = tool.Installer(root)  # canonical path, marker and link checks
        self.root = self.base.root
        if json.loads(self.base.path('.tracker-uid-boot-model.json').read_text()) != BOOT_MARKER:
            raise ValueError('Only a prepared boot simulator is allowed')
        self.debug = self.base.path('persistent/.debug')
        self.fluidd = self.base.path('persistent/.fluidd')
        self.prepared = self.base.path('persistent/.printer_data')
        self.factory = self.base.path('persistent/.factory')
        self.lower = self.base.path('_boot_lower')

    @classmethod
    def prepare(cls, root):
        base = tool.Installer(root)
        if base.path('.klipper-running').exists():
            raise ValueError('Stop simulator before preparing boot model')
        if base.path('_boot_lower').exists():
            raise ValueError('Do not replace the boot baseline')
        if any(base.path(p).exists() for p in tool.TARGETS[:2]) or base.journal.exists():
            raise ValueError('Capture a stock baseline before installing UID')
        tree(base.path('klipper'))  # reject source links before copytree
        base.path('system').mkdir(exist_ok=True)
        inventory(base.path('system'))
        for name in ('persistent', 'persistent/tracker-deployment', '_boot_lower'):
            base.path(name).mkdir(exist_ok=True)
        shutil.copytree(base.path('klipper'), base.path('_boot_lower/klipper'))
        shutil.copytree(base.path('system'), base.path('_boot_lower/system'), symlinks=True)
        shutil.copytree(base.path('printer_data/config'), base.path('_boot_lower/config'))
        for name in ('.fluidd', '.printer_data'):
            tool.atomic(base.path('persistent/' + name), b'')
        tool.atomic(base.path('.tracker-uid-boot-model.json'), tool.canonical(BOOT_MARKER))
        return cls(root)

    def stopped(self):
        if self.base.path('.klipper-running').exists():
            raise ValueError('Stop simulated Klipper before boot/install/rollback')

    def cold_boot(self):
        self.stopped()
        cleared = not self.debug.is_file()
        if cleared:
            for name in ('klipper', 'system'):
                dest = self.base.path(name)
                shutil.rmtree(dest)
                shutil.copytree(self.lower / name, dest, symlinks=True)
        initial = not self.prepared.is_file()
        restore_config = initial or not (self.fluidd.is_file() or self.factory.is_file())
        if restore_config:
            for p in (self.lower / 'config').iterdir():
                if not initial and p.name.startswith('factory'):
                    continue
                if p.is_file():
                    tool.atomic(self.base.path('printer_data/config/' + p.name), p.read_bytes())
            tool.atomic(self.prepared, b'')
        return {'system_layer_cleared': cleared, 'origin_config_restored': restore_config,
                'loadable': self.loadable()}

    def loadable(self):
        """Only the module-presence invariant, NOT a substitute for Klipper startup."""
        main = self.base.path(tool.MAIN).read_bytes()
        if tool.BLOCK not in main:
            return True
        return all(self.base.path(p).is_file() for p in tool.TARGETS[:2])

    def firmware_reset(self, *, clear_debug=True, clear_prepared=True):
        """Model the two marker removals seen in systemUpgrade.sh, not a real OTA."""
        self.stopped()
        if clear_prepared:
            self.prepared.unlink(missing_ok=True)
        if clear_debug:
            self.debug.unlink(missing_ok=True)

    def system_inventory(self, *, lower=False):
        prefix = self.lower if lower else self.root
        return {name + '/' + rel: item
                for name in ('klipper', 'system')
                for rel, item in inventory(prefix / name, exclude_uid=name == 'klipper').items()}

    def firmware_identity(self):
        # Full modeled lower tree/config, not merely the RFID driver's hash.
        return tool.sha(tool.canonical({name: inventory(self.lower / name)
                                       for name in ('klipper', 'system', 'config')}))


class PersistentInstaller(tool.Installer):
    """Same kit transaction, with metadata in the modeled persistent OEM area."""
    def path(self, name):
        if name in ('.tracker-uid-journal.json', '.tracker-uid-install.lock',
                    '.tracker-uid-last-rollback.json', '.tracker-uid-backups') or name.startswith('.tracker-uid-backups/'):
            name = 'persistent/tracker-deployment/' + name
        return super().path(name)

    def rollback(self, *args, **kwargs):
        result = super().rollback(*args, **kwargs)
        tool.sync_dir(self.journal.parent)
        return result


class PersistenceTrial:
    """Explicit whole-overlay persistence experiment; no real-device CLI.

    Order: durable plan -> persistence marker -> module -> cfg -> include.
    Reverse: include -> cfg -> module/cache -> (if unchanged) owned marker.
    An interrupted pending install requires rollback; it is never blindly retried.
    """
    def __init__(self, model):
        self.model = model
        self.installer = PersistentInstaller(model.root)
        self.record = model.base.path('persistent/tracker-deployment/boot-plan.json')

    def plan(self):
        self.model.stopped()
        if self.record.exists():
            raise ValueError('Persistence trial already exists; recover it first')
        debug = self.model.debug
        system = self.model.system_inventory()
        if not debug.exists() and system != self.model.system_inventory(lower=True):
            raise ValueError('Pre-existing volatile system edits: review before retaining the whole overlay')
        data = {
            'schema': 2, 'root': str(self.model.root),
            'scope': 'whole-system-overlay-not-only-rfid',
            'debug_before': tool.encode(debug.read_bytes()) if debug.exists() else None,
            'debug_mode': stat.S_IMODE(debug.stat().st_mode) if debug.exists() else None,
            'system_before': system,
            'firmware_identity': self.model.firmware_identity(),
            'config_policy': self.policy(), 'install': self.installer.plan()}
        return dict(data, revision=tool.sha(tool.canonical(data)))

    def policy(self):
        return {p.name: p.is_file() for p in
                (self.model.fluidd, self.model.prepared, self.model.factory)}

    def read_record(self):
        data = json.loads(self.record.read_text())
        digest = data.pop('revision')
        if (tool.sha(tool.canonical(data)) != digest or data.get('schema') != 2 or
                data.get('root') != str(self.model.root) or
                data.get('scope') != 'whole-system-overlay-not-only-rfid'):
            raise ValueError('Corrupt or foreign persistence record')
        data['revision'] = digest
        return data

    def inspect(self):
        """Read-only recovery decision, usable without the Tracker GUI/database."""
        if not self.record.exists():
            return {'state': 'no-trial', 'automatic_reinstall': False}
        plan = self.read_record()
        changed = differences(plan['system_before'], self.model.system_inventory())
        firmware_changed = plan['firmware_identity'] != self.model.firmware_identity()
        return {'state': 'firmware-changed-review-required' if firmware_changed else
                'foreign-system-edits-review-required' if changed else 'rollback-available',
                'firmware_changed': firmware_changed, 'system_changes': changed,
                'module_present': self.model.base.path(tool.TARGETS[0]).exists(),
                'integration_enabled': tool.BLOCK in self.model.base.path(tool.MAIN).read_bytes(),
                'persistence_enabled': self.model.debug.exists(), 'automatic_reinstall': False}

    def install(self, plan, *, accept_whole_overlay=False, fail_after=None):
        self.model.stopped()
        if not accept_whole_overlay:
            raise ValueError('Explicit acknowledgement of whole-overlay persistence required')
        if plan != self.plan():
            raise ValueError('Stale persistence plan')
        if not self.model.fluidd.is_file() or not self.model.prepared.is_file():
            raise ValueError('This trial requires the observed U1 config policy')
        tool.atomic(self.record, tool.canonical(plan), 0o600)
        if fail_after == 0:
            raise RuntimeError('Injected interruption after durable persistence plan')
        if plan['debug_before'] is None:
            tool.atomic(self.model.debug, b'', 0o644)
        if fail_after == 1:
            raise RuntimeError('Injected interruption after persistence marker')
        self.installer.install(expected_revision=plan['install']['revision'],
                               fail_after=fail_after - 1 if fail_after in (2, 3, 4) else None)
        if fail_after == 5:
            raise RuntimeError('Injected interruption after installed journal')
        return 'installed-in-model'

    def rollback(self, *, fail_after=None):
        self.model.stopped()
        if not self.record.exists():
            return 'no-trial'
        plan = self.read_record()
        if plan['firmware_identity'] != self.model.firmware_identity():
            raise ValueError('Firmware changed: preserve new firmware/config; manual recovery review required')
        self.installer.rollback(fail_after=fail_after if fail_after in (1, 2, 3) else None)
        # Only this extra's cache; never blanket-delete the printer's caches.
        cache = self.model.base.path('klipper/klippy/extras/__pycache__')
        if cache.exists():
            for p in cache.glob('tracker_uid.*.pyc'):
                checked = self.model.base.path(p.relative_to(self.model.root).as_posix())
                checked.unlink()
            tool.sync_dir(cache)
        if fail_after == 4:
            raise RuntimeError('Injected interruption before persistence restoration')
        if plan['debug_before'] is None:
            if self.model.system_inventory() != plan['system_before']:
                raise ValueError('Foreign system edits: keep persistence enabled for review')
            if self.model.debug.exists():
                if self.model.debug.read_bytes() != b'' or stat.S_IMODE(self.model.debug.stat().st_mode) != 0o644:
                    raise ValueError('Persistence marker changed: keep it for review')
                self.model.debug.unlink()
                tool.sync_dir(self.model.debug.parent)
        else:
            # We did not create this setting and never remove or overwrite it.
            if (not self.model.debug.exists() or
                    self.model.debug.read_bytes() != tool.decode(plan['debug_before']) or
                    stat.S_IMODE(self.model.debug.stat().st_mode) != plan['debug_mode']):
                raise ValueError('Pre-existing persistence setting changed; manual review required')
        if fail_after == 5:
            raise RuntimeError('Injected interruption after persistence restoration')
        self.record.unlink()
        tool.sync_dir(self.record.parent)
        return 'rolled-back-in-model'

    def prepare_update(self):
        """Safe modeled update path: remove module integration BEFORE marker reset."""
        self.model.stopped()
        if self.model.system_inventory() != self.model.system_inventory(lower=True):
            raise ValueError('Foreign system edits would be lost on update; preserve and review them first')
        self.rollback()
        if (tool.BLOCK in self.model.base.path(tool.MAIN).read_bytes() or
                any(self.model.base.path(p).exists() for p in tool.TARGETS[:2])):
            raise ValueError('UID integration still active')
        return 'stock-before-update'
