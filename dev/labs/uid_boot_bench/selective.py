"""Conditional pre-Klipper activation from a persistent RFID-only package.

LAB ONLY: the caller models a pre-start hook. No such persistent hook has been
established on the audited U1. This module does NOT install one, alter init,
enable .debug, restart a service, or provide physical-printer deployment.
"""
import json

from dev.labs.uid_boot_bench.model import tool, tree
from dev.labs.uid_boot_bench.optional import OptionalBootTrial, CFG

PACKAGE = 'persistent/tracker-deployment/selective-package.json'
ENABLED = 'persistent/tracker-deployment/selective-enabled'
ENABLE_VALUE = b'tracker-uid-selective-trial-v1\n'


class SelectiveBootTrial:
    requires_global_persistence = False

    def __init__(self, model):
        self.model = model
        self.base = model.base
        self.optional = OptionalBootTrial(model)

    def stage(self, *, fail_after=None):
        """Stage while stopped. Explicit enable is the final durable operation."""
        with self.base.locked():
            self.model.stopped()
            if self.model.debug.exists() != self.requires_global_persistence:
                raise ValueError('Unexpected whole-overlay persistence policy')
            if any(self.base.path(n).exists() for n in (PACKAGE, ENABLED)):
                raise ValueError('Recover the existing selective package first')
            self.base.plan()
            module = tool.MODULE.read_bytes()
            compile(module, 'tracker_uid.py', 'exec')  # syntax only; no execution
            data = dict(schema=1, root=str(self.model.root), module=tool.encode(module),
                        driver_sha256=tool.sha(self.base.path(tool.DRIVER).read_bytes()))
            tool.atomic(self.base.path(PACKAGE), tool.canonical(dict(
                data, revision=tool.sha(tool.canonical(data)))), 0o600)
            if fail_after == 0:
                raise RuntimeError('Interrupted after persistent package')
            self.optional.install()
            # Keep initial installation consistent with the pre-start path: only
            # activate() writes the final activating cfg after enabled is set.
            self.base.path(CFG).unlink()
            tool.sync_dir(self.base.path(CFG).parent)
            if fail_after == 1:
                raise RuntimeError('Interrupted before explicit enable')
            tool.atomic(self.base.path(ENABLED), ENABLE_VALUE, 0o600)
            if fail_after == 2:
                raise RuntimeError('Interrupted after explicit enable')

    def record(self):
        data = json.loads(self.optional.record.read_text())
        revision = data.pop('revision')
        if (tool.sha(tool.canonical(data)) != revision or data.get('schema') != 1
                or data.get('root') != str(self.model.root)
                or data.get('block') != tool.encode(self.optional.block)):
            raise ValueError('Invalid activation ownership record')
        return data

    def activate(self, *, fail_after=None):
        """Run ONLY between modeled cleanup and Klipper, never on a live printer.

        An exception is a stop/review result, NOT permission to start Klipper.
        A disabled result promises only that our activating cfg is absent; it
        does not certify unrelated user configuration or service lifecycle.
        """
        with self.base.locked():
            self.model.stopped()
            if not self.optional.record.exists():
                if self.base.path(CFG).exists():
                    raise ValueError('Activating cfg exists without an ownership record')
                return dict(state='disabled', reason='not-staged')
            record = self.record()
            cfg = self.base.path(CFG)
            if cfg.exists() and tool.sha(cfg.read_bytes()) != record['cfg_sha256']:
                raise ValueError('Foreign activating cfg; do not overwrite or start automatically')
            # Withdraw activation before checking/replacing the module. Even an
            # interruption after this point leaves the exact-name include empty.
            cfg.unlink(missing_ok=True)
            tool.sync_dir(cfg.parent)
            if fail_after == 0:
                raise RuntimeError('Interrupted after activation withdrawal')

            def disabled(reason):
                return dict(state='disabled', reason=reason)

            if 'rollback_main_after' in record:
                return disabled('rollback-in-progress')
            enabled = self.base.path(ENABLED)
            if not enabled.exists() or enabled.read_bytes() != ENABLE_VALUE:
                return disabled('not-enabled')
            if self.model.debug.exists() != self.requires_global_persistence:
                return disabled('unexpected-global-persistence')
            if record['firmware_identity'] != self.model.firmware_identity():
                return disabled('firmware-changed')
            if tool.sha(tool.CONFIG) != record['cfg_sha256']:
                return disabled('activation-build-changed')
            # Config edits need a fresh review. In particular, do not reactivate
            # after a vendor reset or after a different include graph is installed.
            expected_main = self.optional.configured_main(tool.decode(record['main_before']))
            if self.base.path(tool.MAIN).read_bytes() != expected_main:
                return disabled('configuration-changed')
            try:
                data = json.loads(self.base.path(PACKAGE).read_text())
                revision = data.pop('revision')
                if (tool.sha(tool.canonical(data)) != revision or data.get('schema') != 1
                        or data.get('root') != str(self.model.root)):
                    return disabled('package-invalid')
                module = tool.decode(data['module'])
                if tool.sha(module) != record['module_sha256']:
                    return disabled('package-module-changed')
                compile(module, 'tracker_uid.py', 'exec')
            except (OSError, ValueError, KeyError, TypeError, SyntaxError):
                return disabled('package-invalid')
            driver = tool.sha(self.base.path(tool.DRIVER).read_bytes())
            if driver != data['driver_sha256'] or driver not in tool.supported_drivers():
                return disabled('driver-changed')
            if tree(self.base.path('klipper')) != tree(self.model.lower / 'klipper'):
                return disabled('klipper-source-changed')
            target = self.base.path(tool.TARGETS[0])
            if target.exists() and tool.sha(target.read_bytes()) != record['module_sha256']:
                return disabled('foreign-module')
            tool.atomic(target, module, 0o644)
            if fail_after == 1:
                raise RuntimeError('Interrupted after module restoration')
            # Last write makes the checked pair visible to a future Klipper start.
            tool.atomic(cfg, tool.CONFIG, 0o644)
            if fail_after == 2:
                raise RuntimeError('Interrupted after activation commit')
            return dict(state='active', reason='verified-package')

    def rollback(self, *, fail_after=None):
        with self.base.locked():
            self.model.stopped()
            self.base.path(ENABLED).unlink(missing_ok=True)
            tool.sync_dir(self.base.path(ENABLED).parent)
            if fail_after == 0:
                raise RuntimeError('Interrupted after disabling future activation')
            self.optional.rollback(fail_after=fail_after)
            self.base.path(PACKAGE).unlink(missing_ok=True)
            tool.sync_dir(self.base.path(PACKAGE).parent)
