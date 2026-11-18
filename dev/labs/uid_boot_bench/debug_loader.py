"""Guarded .debug installation in MARKED SIMULATORS ONLY; no physical U1 CLI.

The init wrapper is exercised against a harmless stock-service stand-in. No vendor
service, MCU command, mount, SSH, or printer restart is executed by this module.
"""
import argparse
import configparser
from functools import wraps
import json
from pathlib import Path
import shlex
import shutil
import stat
import sys

from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import SelectiveBootTrial, ENABLED

SERVICE = 'system/init.d/S60klipper'
RECORD = 'persistent/tracker-deployment/debug-loader-plan.json'
KIT = 'persistent/tracker-deployment/debug-loader-kit'
BACKUP = 'persistent/tracker-deployment/debug-loader-backup'


def locked_transaction(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        import fcntl
        path = self.base.path('persistent/tracker-deployment/debug-loader.lock')
        with path.open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.model.stopped()
            return method(self, *args, **kwargs)
    return call


class DebugActivation(SelectiveBootTrial):
    requires_global_persistence = True


def export_kit(destination):
    """Independent stdlib activation/recovery code. Hashes detect corruption, not tampering."""
    repo = Path(__file__).resolve().parents[3]
    sources = {'scripts/rfid_module_tool.py': repo / 'scripts/rfid_module_tool.py',
               'scripts/tracker_uid.py': tool.MODULE}
    for name in ('model', 'optional', 'selective', 'debug_loader'):
        sources[f'dev/labs/uid_boot_bench/{name}.py'] = Path(__file__).with_name(name + '.py')
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, source in sources.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tool.atomic(target, source.read_bytes())
        hashes[name] = tool.sha(target.read_bytes())
    bootstrap = '''import hashlib, json, sys
from pathlib import Path
root = Path(__file__).resolve().parent
expected = EXPECTED
try:
    for name, digest in expected.items():
        p = root / name
        if any(q.is_symlink() for q in (p, *p.parents)) or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('Loader kit integrity failure: ' + name)
except (OSError, ValueError) as exc:
    print(json.dumps({'state': 'review-required', 'error': str(exc)}))
    raise SystemExit(1)
sys.path.insert(0, str(root))
from dev.labs.uid_boot_bench.debug_loader import main
raise SystemExit(main())
'''.replace('EXPECTED', repr(hashes))
    tool.atomic(destination / 'launch.py', bootstrap.encode())
    hashes['launch.py'] = tool.sha(bootstrap.encode())
    tool.atomic(destination / 'manifest.json', tool.canonical({'schema': 1, 'files': hashes}))
    return hashes


class DebugLoaderTrial:
    def __init__(self, model):
        self.model, self.base = model, model.base
        self.activation = DebugActivation(model)
        self.record = self.base.path(RECORD)

    def wrapper(self, interpreter):
        launcher = self.base.path(KIT + '/launch.py')
        stock = self.base.path(BACKUP + '/S60klipper')
        command = ' '.join(shlex.quote(str(v)) for v in
                           (interpreter, '-I', launcher, 'activate', '--simulator-root', self.model.root))
        return ('#!/bin/sh\n# TRACKER UID LAB PRE-START WRAPPER\n'
                'case "$1" in\nstart) ' + command + ' || exit $? ;;\n'
                'stop|status) ;;\n*) echo "Use explicit stopped start; laboratory wrapper" >&2; exit 2 ;;\nesac\n'
                'exec ' + shlex.quote(str(stock)) + ' "$@"\n').encode()

    def plan(self):
        self.model.stopped()
        if any(self.base.path(p).exists() for p in (RECORD, KIT, BACKUP)):
            raise ValueError('Existing debug-loader transaction or retained recovery files; review first')
        activation_plan = self.base.plan()
        for p in (self.activation.optional.record, self.base.path(ENABLED)):
            if p.exists():
                raise ValueError('Existing activation transaction')
        service = self.base.path(SERVICE)
        if not service.is_file() or not service.stat().st_mode & 0o111:
            raise ValueError('Reviewed executable stock-service fixture required')
        data = dict(schema=1, root=str(self.model.root), scope='whole-overlay',
                    activation_revision=activation_plan['revision'],
                    firmware_identity=self.model.firmware_identity(),
                    system_before=self.model.system_inventory(),
                    lower_before=self.model.system_inventory(lower=True),
                    main_before=tool.encode(self.base.path(tool.MAIN).read_bytes()),
                    debug_before=tool.encode(self.model.debug.read_bytes()) if self.model.debug.exists() else None,
                    debug_mode=stat.S_IMODE(self.model.debug.stat().st_mode) if self.model.debug.exists() else None,
                    stock=tool.encode(service.read_bytes()), stock_mode=stat.S_IMODE(service.stat().st_mode),
                    interpreter=sys.executable, wrapper=tool.encode(self.wrapper(sys.executable)),
                    config_policy={p.name: p.is_file() for p in
                                   (self.model.fluidd, self.model.prepared, self.model.factory)})
        return dict(data, revision=tool.sha(tool.canonical(data)))

    def read(self):
        data = json.loads(self.record.read_text())
        digest = data.pop('revision')
        if (data.get('schema') != 1 or data.get('root') != str(self.model.root)
                or data.get('scope') != 'whole-overlay' or tool.sha(tool.canonical(data)) != digest):
            raise ValueError('Invalid debug-loader record')
        return data

    @locked_transaction
    def install(self, plan, *, accept_whole_overlay=False, accept_existing_changes=False, fail_after=None):
        self.model.stopped()
        if not accept_whole_overlay:
            raise ValueError('Explicit whole-overlay acknowledgement required')
        if plan != self.plan():
            raise ValueError('Stale debug-loader plan')
        if plan['system_before'] != plan['lower_before'] and not accept_existing_changes:
            raise ValueError('Review existing system changes before retaining them')
        if not self.model.fluidd.is_file() or not self.model.prepared.is_file():
            raise ValueError('Unsupported config restoration policy')
        tool.atomic(self.record, tool.canonical(plan), 0o600)
        if fail_after == 0:
            raise RuntimeError('Interrupted after plan')
        backup = self.base.path(BACKUP)
        backup.mkdir()
        # Materialized bench backup, not a kernel OverlayFS/ACL/xattrs backup.
        for name in ('system', 'klipper'):
            shutil.copytree(self.base.path(name), backup / name, symlinks=True)
        tool.atomic(backup / 'printer.cfg', tool.decode(plan['main_before']), 0o600)
        tool.atomic(backup / 'S60klipper', tool.decode(plan['stock']), plan['stock_mode'])
        tool.atomic(backup / 'inventory.json', tool.canonical(plan['system_before']), 0o600)
        export_kit(self.base.path(KIT))
        if fail_after == 1:
            raise RuntimeError('Interrupted after recovery kit and backup')
        if plan['debug_before'] is None:
            tool.atomic(self.model.debug, b'', 0o644)
        if fail_after == 2:
            raise RuntimeError('Interrupted after persistence marker')
        # Install the guard before making the optional config include visible.
        tool.atomic(self.base.path(SERVICE), tool.decode(plan['wrapper']), plan['stock_mode'])
        if fail_after == 3:
            raise RuntimeError('Interrupted after init guard')
        self.activation.stage()
        if fail_after == 4:
            raise RuntimeError('Interrupted after activation staging')
        # No cfg is active until the wrapper invokes activate on the next start.
        return dict(state='staged', scope='whole-overlay', physical_installation=False)

    @locked_transaction
    def activate(self):
        self.model.stopped()
        plan = self.read()
        if self.base.path(SERVICE).read_bytes() != tool.decode(plan['wrapper']):
            raise ValueError('Init wrapper changed; review required')
        if self.base.path(BACKUP + '/S60klipper').read_bytes() != tool.decode(plan['stock']):
            raise ValueError('Stock-service backup changed; do not execute')
        # Handles an interrupted install before stage() created its record.
        result = self.activation.activate()
        tool.atomic(self.base.path('persistent/tracker-deployment/debug-loader-status.json'),
                    tool.canonical(result), 0o600)
        return result

    @locked_transaction
    def rollback(self, *, fail_after=None):
        self.model.stopped()
        if not self.record.exists():
            return dict(state='no-trial')
        plan = self.read()
        if plan['firmware_identity'] != self.model.firmware_identity():
            raise ValueError('Firmware changed; never restore old startup/config automatically')
        # Disable future activation first. Preserve transaction for interrupted recovery.
        self.base.path(ENABLED).unlink(missing_ok=True)
        tool.sync_dir(self.base.path(ENABLED).parent)
        if fail_after == 0:
            raise RuntimeError('Interrupted after disable')
        self.activation.rollback()
        if fail_after == 1:
            raise RuntimeError('Interrupted after RFID removal')
        current = self.base.path(SERVICE).read_bytes()
        if current not in (tool.decode(plan['wrapper']), tool.decode(plan['stock'])):
            raise ValueError('Foreign startup changes retained; persistence must stay enabled')
        if current != tool.decode(plan['stock']):
            tool.atomic(self.base.path(SERVICE), tool.decode(plan['stock']), plan['stock_mode'])
        if fail_after == 2:
            raise RuntimeError('Interrupted after stock startup restoration')
        # Removing .debug must not discard either pre-existing or later system edits.
        if plan['debug_before'] is None:
            if (self.model.system_inventory() != plan['system_before'] or
                    plan['system_before'] != plan['lower_before']):
                return dict(state='rfid-removed-persistence-retained', reason='system-changes-require-review')
            if self.model.debug.exists():
                if self.model.debug.read_bytes() != b'' or stat.S_IMODE(self.model.debug.stat().st_mode) != 0o644:
                    raise ValueError('Debug marker changed; retain for review')
                self.model.debug.unlink()
                tool.sync_dir(self.model.debug.parent)
        elif (not self.model.debug.exists() or self.model.debug.read_bytes() != tool.decode(plan['debug_before'])
              or stat.S_IMODE(self.model.debug.stat().st_mode) != plan['debug_mode']):
            raise ValueError('Pre-existing debug setting changed; retain for review')
        if fail_after == 3:
            raise RuntimeError('Interrupted after debug restoration')
        self.record.unlink()
        tool.sync_dir(self.record.parent)
        return dict(state='rolled-back', recovery_files='retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'install', 'activate', 'rollback', 'inspect'])
    parser.add_argument('--simulator-root', type=Path, required=True)
    parser.add_argument('--reviewed-revision', help='Revision returned by plan')
    parser.add_argument('--accept-whole-overlay', action='store_true')
    parser.add_argument('--accept-existing-changes', action='store_true')
    args = parser.parse_args()
    try:
        trial = DebugLoaderTrial(BootModel(args.simulator_root))
        if args.action in ('plan', 'install'):
            include = 'include /extras/[t]racker_uid_boot.cfg'
            header = configparser.RawConfigParser.SECTCRE.match('[' + include + ']')
            if header is None or header.group('header') != include:
                raise ValueError('Python configparser truncates the RFID include; use a compatible interpreter')
            plan = trial.plan()
            driver = tool.sha(trial.base.path(tool.DRIVER).read_bytes())
            if tool.supported_drivers().get(driver) != '2.1.0.157':
                raise ValueError('This package targets the reviewed 2.1.0.157 driver')
            if args.action == 'plan':
                result = dict(revision=plan['revision'], driver_sha256=driver,
                              existing_changes=plan['system_before'] != plan['lower_before'],
                              debug_present=plan['debug_before'] is not None,
                              service=SERVICE, config=tool.MAIN, scope=plan['scope'],
                              physical_installation=False)
            else:
                if args.reviewed_revision != plan['revision']:
                    raise ValueError('Installation requires the current reviewed revision')
                trial.install(plan, accept_whole_overlay=args.accept_whole_overlay,
                              accept_existing_changes=args.accept_existing_changes)
                result = dict(state='staged', recovery=KIT + '/launch.py')
        elif args.action == 'inspect':
            result = dict(staged=trial.record.exists(), physical_installation=False)
        elif args.action == 'rollback':
            result = trial.rollback()
        else:
            result = trial.activate()
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(state='review-required', error=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
