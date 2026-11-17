"""Conditional pre-start hook: persistent package, no global overlay persistence."""
import json
import sys

import pytest

from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import SelectiveBootTrial, PACKAGE, ENABLED, CFG

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX boot-policy laboratory')


@pytest.fixture
def model(tmp_path, monkeypatch):
    root = tmp_path.resolve() / 'u1'
    for name in ('klipper/klippy/extras', 'printer_data/config', 'system'):
        (root / name).mkdir(parents=True)
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    driver = b'# synthetic driver\n'
    (root / tool.DRIVER).write_bytes(driver)
    (root / tool.MAIN).write_bytes(b'[printer]\nkinematics: none\n')
    (root / 'system/network.conf').write_bytes(b'stock\n')
    monkeypatch.setattr(tool, 'supported_drivers', lambda: {tool.sha(driver): 'fixture'})
    return BootModel.prepare(root)


def test_package_alone_is_not_a_persistent_boot_hook(model):
    trial = SelectiveBootTrial(model)
    trial.stage()
    trial.activate()
    model.cold_boot()  # deliberately NO call to activate
    assert model.base.path(PACKAGE).exists()
    assert not model.base.path(CFG).exists()
    assert not model.base.path(tool.TARGETS[0]).exists()
    assert not model.debug.exists()


def test_conditional_hook_survives_repeated_cleanup_without_preserving_other_files(model):
    before = model.base.path(tool.MAIN).read_bytes()
    trial = SelectiveBootTrial(model)
    trial.stage()
    for _ in range(3):
        model.base.path('system/network.conf').write_bytes(b'volatile change\n')
        model.cold_boot()
        # Recreate controller: no Python in-memory state carries activation.
        trial = SelectiveBootTrial(BootModel(model.root))
        assert trial.activate()['state'] == 'active'
        assert model.base.path('system/network.conf').read_bytes() == b'stock\n'
        assert model.base.path(CFG).read_bytes() == tool.CONFIG
        assert not model.debug.exists()
    trial.rollback()
    assert model.base.path(tool.MAIN).read_bytes() == before
    assert not model.base.path(PACKAGE).exists()
    assert not model.base.path(ENABLED).exists()
    assert trial.activate()['reason'] == 'not-staged'


@pytest.mark.parametrize('boundary', range(3))
def test_interrupted_staging_recovers_without_global_persistence(model, boundary):
    before = model.base.path(tool.MAIN).read_bytes()
    trial = SelectiveBootTrial(model)
    with pytest.raises(RuntimeError):
        trial.stage(fail_after=boundary)
    model.cold_boot()
    state = SelectiveBootTrial(BootModel(model.root)).activate()['state']
    assert state == ('active' if boundary == 2 else 'disabled')
    trial.rollback()
    assert model.base.path(tool.MAIN).read_bytes() == before


@pytest.mark.parametrize('boundary', range(3))
def test_interrupted_activation_never_leaves_cfg_without_verified_module(model, boundary):
    trial = SelectiveBootTrial(model)
    trial.stage()
    model.cold_boot()
    with pytest.raises(RuntimeError):
        trial.activate(fail_after=boundary)
    assert model.base.path(CFG).exists() == (boundary == 2)
    if model.base.path(CFG).exists():
        assert model.base.path(tool.TARGETS[0]).read_bytes() == tool.MODULE.read_bytes()
    assert trial.activate()['state'] == 'active'
    trial.rollback()


@pytest.mark.parametrize('boundary', range(4))
def test_interrupted_rollback_cannot_reenable_on_next_boot(model, boundary):
    before = model.base.path(tool.MAIN).read_bytes()
    trial = SelectiveBootTrial(model)
    trial.stage()
    trial.activate()
    with pytest.raises(RuntimeError):
        trial.rollback(fail_after=boundary)
    model.cold_boot()
    assert trial.activate()['state'] == 'disabled'
    assert not model.base.path(CFG).exists()
    SelectiveBootTrial(BootModel(model.root)).rollback()
    assert model.base.path(tool.MAIN).read_bytes() == before


@pytest.mark.parametrize('problem,reason', [
    ('package-missing', 'package-invalid'), ('package-corrupt', 'package-invalid'),
    ('module-corrupt', 'foreign-module'), ('driver-changed', 'driver-changed'),
    ('firmware-changed', 'firmware-changed'), ('config-changed', 'configuration-changed'),
    ('enable-missing', 'not-enabled'), ('debug', 'unexpected-global-persistence'),
    ('source-changed', 'klipper-source-changed'),
])
def test_refusal_withdraws_only_own_activation(model, problem, reason):
    trial = SelectiveBootTrial(model)
    trial.stage()
    trial.activate()
    if problem == 'package-missing':
        model.base.path(PACKAGE).unlink()
    elif problem == 'package-corrupt':
        model.base.path(PACKAGE).write_bytes(b'bad json')
    elif problem == 'module-corrupt':
        model.base.path(tool.TARGETS[0]).write_bytes(b'# foreign\n')
    elif problem == 'driver-changed':
        model.base.path(tool.DRIVER).write_bytes(b'# new driver\n')
    elif problem == 'firmware-changed':
        (model.lower / 'system/new-service').write_bytes(b'new firmware\n')
    elif problem == 'config-changed':
        model.base.path(tool.MAIN).write_bytes(model.base.path(tool.MAIN).read_bytes() + b'# later edit\n')
    elif problem == 'enable-missing':
        model.base.path(ENABLED).unlink()
    elif problem == 'debug':
        model.debug.write_bytes(b'foreign marker')
    elif problem == 'source-changed':
        model.base.path('klipper/klippy/new.py').write_bytes(b'# foreign source\n')
    main_before = model.base.path(tool.MAIN).read_bytes()
    assert trial.activate() == dict(state='disabled', reason=reason)
    assert not model.base.path(CFG).exists()
    assert model.base.path(tool.MAIN).read_bytes() == main_before
    if problem == 'module-corrupt':
        assert model.base.path(tool.TARGETS[0]).read_bytes() == b'# foreign\n'


def test_foreign_cfg_is_not_erased_and_does_not_authorize_automatic_start(model):
    trial = SelectiveBootTrial(model)
    trial.stage()
    model.base.path(CFG).write_bytes(b'# someone else owns this\n')
    with pytest.raises(ValueError, match='Foreign activating cfg'):
        trial.activate()
    assert model.base.path(CFG).read_bytes() == b'# someone else owns this\n'


def test_live_process_and_concurrent_controller_cannot_activate(model):
    trial = SelectiveBootTrial(model)
    trial.stage()
    model.base.path('.klipper-running').write_bytes(b'running')
    with pytest.raises(ValueError, match='Stop'):
        trial.activate()
    model.base.path('.klipper-running').unlink()
    with model.base.locked(), pytest.raises(BlockingIOError):
        trial.activate()


def test_vendor_config_reset_does_not_silently_restore_old_config(model):
    before = model.base.path(tool.MAIN).read_bytes()
    trial = SelectiveBootTrial(model)
    trial.stage()
    model.firmware_reset()
    model.cold_boot()
    assert trial.activate()['reason'] == 'configuration-changed'
    assert model.base.path(tool.MAIN).read_bytes() == before
    trial.rollback()


def test_symlink_payload_never_reads_external_file(model, tmp_path):
    trial = SelectiveBootTrial(model)
    trial.stage()
    model.base.path(PACKAGE).unlink()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'do not modify')
    (model.root / PACKAGE).symlink_to(outside)
    assert trial.activate()['reason'] == 'package-invalid'
    assert outside.read_bytes() == b'do not modify'
