"""Debug loader transaction, boot guard and recovery in disposable model roots."""
import json
import subprocess
import sys

import pytest

from dev.labs.uid_boot_bench.debug_loader import DebugLoaderTrial, SERVICE, KIT, BACKUP
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import PACKAGE, CFG

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX boot-policy laboratory')


@pytest.fixture
def model(tmp_path, monkeypatch):
    root = tmp_path.resolve() / 'debug bench'
    for name in ('klipper/klippy/extras', 'printer_data/config', 'system/init.d'):
        (root / name).mkdir(parents=True)
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    raw = b'# synthetic driver\n'
    (root / tool.DRIVER).write_bytes(raw)
    module = tmp_path / 'tracker_uid.py'
    module.write_text('SUPPORTED_DRIVERS = ' + repr({tool.sha(raw): 'test fixture'}) + '\n')
    monkeypatch.setattr(tool, 'MODULE', module)
    (root / tool.MAIN).write_bytes(b'[printer]\nkinematics: none\n')
    # The real vendor service is NEVER executed by these tests.
    (root / SERVICE).write_bytes(b'#!/bin/sh\nprintf "STOCK_START:%s\\n" "$1"\n')
    (root / SERVICE).chmod(0o755)
    return BootModel.prepare(root)


def install(model, **kw):
    trial = DebugLoaderTrial(model)
    trial.install(trial.plan(), accept_whole_overlay=True, **kw)
    return trial


def dispatch(model):
    return subprocess.run([str(model.base.path(SERVICE)), 'start'],
                          text=True, capture_output=True, timeout=15)


def test_explicit_scope_and_current_plan_required(model):
    trial = DebugLoaderTrial(model)
    plan = trial.plan()
    with pytest.raises(ValueError, match='acknowledgement'):
        trial.install(plan)
    model.base.path(tool.MAIN).write_bytes(b'# changed\n')
    with pytest.raises(ValueError, match='Stale'):
        trial.install(plan, accept_whole_overlay=True)
    assert not model.debug.exists()


def test_persistent_wrapper_invokes_independent_guard_before_stock(model):
    trial = install(model)
    assert not model.base.path(CFG).exists()
    for _ in range(2):
        model.cold_boot()
        result = dispatch(model)
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.splitlines()
        assert json.loads(lines[0])['state'] == 'active'
        assert lines[1] == 'STOCK_START:start'
        assert model.base.path(CFG).exists()
    assert trial.rollback()['state'] == 'rolled-back'
    assert dispatch(model).stdout == 'STOCK_START:start\n'
    assert not model.debug.exists()


@pytest.mark.parametrize('boundary', range(5))
def test_install_interruption_can_boot_and_rollback(model, boundary):
    trial = DebugLoaderTrial(model)
    with pytest.raises(RuntimeError):
        trial.install(trial.plan(), accept_whole_overlay=True, fail_after=boundary)
    model.cold_boot()
    result = dispatch(model)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'STOCK_START:start' in result.stdout
    assert trial.rollback()['state'] == 'rolled-back'
    assert not model.debug.exists()
    assert model.base.path(tool.MAIN).read_bytes() == b'[printer]\nkinematics: none\n'


@pytest.mark.parametrize('boundary', range(4))
def test_rollback_interruption_does_not_reactivate(model, boundary):
    trial = install(model)
    assert trial.activate()['state'] == 'active'
    with pytest.raises(RuntimeError):
        trial.rollback(fail_after=boundary)
    model.cold_boot()
    result = dispatch(model)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not model.base.path(CFG).exists()
    assert trial.rollback()['state'] == 'rolled-back'


@pytest.mark.parametrize('problem', ['package', 'driver', 'firmware', 'main', 'module'])
def test_known_failures_withdraw_own_cfg_and_allow_stock(model, problem):
    trial = install(model)
    trial.activate()
    paths = dict(package=PACKAGE, driver=tool.DRIVER, main=tool.MAIN, module=tool.TARGETS[0])
    if problem == 'firmware':
        (model.lower / 'system/new-firmware').write_bytes(b'new')
    else:
        model.base.path(paths[problem]).write_bytes(b'# changed\n')
    result = dispatch(model)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[0])['state'] == 'disabled'
    assert 'STOCK_START:start' in result.stdout
    assert not model.base.path(CFG).exists()


@pytest.mark.parametrize('problem', ['kit', 'stock-backup', 'foreign-cfg'])
def test_untrusted_startup_state_cannot_launch_stock_blindly(model, problem):
    trial = install(model)
    trial.activate()
    path = {'kit': KIT + '/dev/labs/uid_boot_bench/selective.py',
            'stock-backup': BACKUP + '/S60klipper', 'foreign-cfg': CFG}[problem]
    model.base.path(path).write_bytes(b'# foreign\n')
    result = dispatch(model)
    assert result.returncode != 0
    assert 'STOCK_START' not in result.stdout


def test_debug_loss_restores_stock_and_optional_include_is_inert(model):
    install(model).activate()
    model.debug.unlink()
    model.cold_boot()
    assert dispatch(model).stdout == 'STOCK_START:start\n'
    assert not model.base.path(CFG).exists()
    assert not model.base.path(tool.TARGETS[0]).exists()


def test_existing_volatile_changes_require_review_and_survive_rollback(model):
    model.base.path('system/wifi.conf').write_bytes(b'user-owned fixture\n')
    trial = DebugLoaderTrial(model)
    with pytest.raises(ValueError, match='Review existing'):
        trial.install(trial.plan(), accept_whole_overlay=True)
    trial = install(model, accept_existing_changes=True)
    assert model.base.path(BACKUP + '/system/wifi.conf').read_bytes() == b'user-owned fixture\n'
    assert trial.rollback()['state'] == 'rfid-removed-persistence-retained'
    assert model.debug.exists()
    model.cold_boot()
    assert model.base.path('system/wifi.conf').read_bytes() == b'user-owned fixture\n'


def test_later_changes_survive_and_second_rollback_is_safe(model):
    trial = install(model)
    extra = model.base.path('system/user-change')
    extra.write_bytes(b'keep')
    assert trial.rollback()['state'] == 'rfid-removed-persistence-retained'
    assert model.debug.exists() and extra.read_bytes() == b'keep'
    extra.unlink()  # explicit bench-owner cleanup, never automatic recovery
    assert trial.rollback()['state'] == 'rolled-back'


def test_preexisting_debug_is_not_removed(model):
    model.debug.write_bytes(b'user-owned')
    model.debug.chmod(0o600)
    trial = install(model)
    trial.rollback()
    assert model.debug.read_bytes() == b'user-owned'
    assert model.debug.stat().st_mode & 0o777 == 0o600


def test_changed_firmware_prevents_old_rollback(model):
    trial = install(model)
    (model.lower / 'system/firmware').write_bytes(b'new')
    with pytest.raises(ValueError, match='Firmware changed'):
        trial.rollback()
    assert model.debug.exists()


def test_running_bench_rejects_mutations(model):
    trial = install(model)
    model.base.path('.klipper-running').write_bytes(b'running')
    for operation in (trial.activate, trial.rollback):
        with pytest.raises(ValueError, match='Stop simulated'):
            operation()


def test_changed_package_invalidates_install_plan(model):
    trial = DebugLoaderTrial(model)
    plan = trial.plan()
    tool.MODULE.write_text(tool.MODULE.read_text() + '# different build\n')
    with pytest.raises(ValueError, match='Stale'):
        trial.install(plan, accept_whole_overlay=True)
    assert not model.debug.exists()


def test_concurrent_loader_and_recovery_are_rejected(model):
    import fcntl
    trial = install(model)
    with model.base.path('persistent/tracker-deployment/debug-loader.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for operation in (trial.activate, trial.rollback):
            with pytest.raises(BlockingIOError):
                operation()
        result = dispatch(model)
        assert result.returncode != 0 and 'STOCK_START' not in result.stdout
    assert trial.activate()['state'] == 'active'
