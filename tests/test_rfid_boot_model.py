"""Boot policy and transaction-boundary fault injection, in disposable roots only."""
import json
import sys

import pytest

from dev.labs.uid_boot_bench.model import BootModel, PersistenceTrial, tool

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX boot-policy laboratory')


@pytest.fixture
def model(tmp_path, monkeypatch):
    root = tmp_path.resolve() / 'u1'
    for name in ('klipper/klippy/extras', 'printer_data/config'):
        (root / name).mkdir(parents=True)
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    raw = b'# synthetic boot-policy driver; not executed\n'
    (root / tool.DRIVER).write_bytes(raw)
    (root / tool.MAIN).write_bytes(b'[printer]\nkinematics: none\n')
    monkeypatch.setattr(tool, 'supported_drivers', lambda: {tool.sha(raw): 'boot-fixture'})
    return BootModel.prepare(root)


def trial_install(model):
    trial = PersistenceTrial(model)
    trial.install(trial.plan(), accept_whole_overlay=True)
    return trial


def test_naive_install_breaks_after_cold_boot(model):
    model.base.install()
    assert model.loadable()
    result = model.cold_boot()
    assert result == {'system_layer_cleared': True, 'origin_config_restored': False, 'loadable': False}
    assert tool.BLOCK in model.base.path(tool.MAIN).read_bytes()
    assert not model.base.path(tool.TARGETS[0]).exists()


def test_global_persistence_is_never_implicit(model):
    trial = PersistenceTrial(model)
    with pytest.raises(ValueError, match='Explicit acknowledgement'):
        trial.install(trial.plan())
    assert not model.debug.exists() and not trial.record.exists()
    assert not trial.installer.journal.exists()


def test_persistent_candidate_survives_repeated_boot_then_exact_rollback(model):
    before = model.base.path(tool.MAIN).read_bytes()
    trial = trial_install(model)
    for _ in range(3):
        assert model.cold_boot()['loadable']
        assert trial.installer.inspect()['files_match']
        assert trial.installer.read_journal()['state'] == 'installed'
    trial.rollback()
    assert model.base.path(tool.MAIN).read_bytes() == before
    assert not model.debug.exists()
    assert model.cold_boot()['loadable']
    assert not trial.record.exists()
    assert trial.rollback() == 'no-trial'


@pytest.mark.parametrize('stage', range(6))
def test_power_cut_after_each_install_boundary_can_boot_and_rollback(model, stage):
    original = model.base.path(tool.MAIN).read_bytes()
    trial = PersistenceTrial(model)
    with pytest.raises(RuntimeError):
        trial.install(trial.plan(), accept_whole_overlay=True, fail_after=stage)
    assert model.cold_boot()['loadable']
    # New controller instance, with only persistent transaction data.
    recovered = PersistenceTrial(BootModel(model.root))
    recovered.rollback()
    assert model.cold_boot()['loadable']
    assert model.base.path(tool.MAIN).read_bytes() == original
    assert not model.debug.exists()


@pytest.mark.parametrize('stage', range(1, 6))
def test_power_cut_after_each_rollback_boundary_can_boot_and_resume(model, stage):
    original = model.base.path(tool.MAIN).read_bytes()
    trial = trial_install(model)
    with pytest.raises(RuntimeError):
        trial.rollback(fail_after=stage)
    assert model.cold_boot()['loadable']
    PersistenceTrial(BootModel(model.root)).rollback()
    assert model.cold_boot()['loadable']
    assert model.base.path(tool.MAIN).read_bytes() == original


def test_rollback_keeps_foreign_system_changes_and_debug_marker(model):
    trial = trial_install(model)
    foreign = model.base.path('klipper/klippy/extras/other_module.py')
    foreign.write_text('# user installation\n')
    with pytest.raises(ValueError, match='Foreign system edits'):
        trial.rollback()
    assert tool.BLOCK not in model.base.path(tool.MAIN).read_bytes()
    assert model.debug.exists() and trial.record.exists()
    assert model.cold_boot()['loadable']
    assert foreign.read_text() == '# user installation\n'


def test_preexisting_debug_setting_is_preserved(model):
    model.debug.write_bytes(b'pre-existing user marker\n')
    model.debug.chmod(0o600)
    trial = trial_install(model)
    trial.rollback()
    assert model.debug.read_bytes() == b'pre-existing user marker\n'
    assert model.debug.stat().st_mode & 0o777 == 0o600


def test_stale_plan_and_changed_policy_are_rejected(model):
    trial = PersistenceTrial(model)
    plan = trial.plan()
    model.fluidd.unlink()
    with pytest.raises(ValueError, match='Stale'):
        trial.install(plan, accept_whole_overlay=True)
    assert not trial.record.exists() and not model.debug.exists()


def test_live_simulator_cannot_install_boot_or_rollback(model):
    trial = PersistenceTrial(model)
    plan = trial.plan()
    model.base.path('.klipper-running').write_text('owned simulated PID')
    for call in (model.cold_boot, trial.rollback,
                 lambda: trial.install(plan, accept_whole_overlay=True)):
        with pytest.raises(ValueError, match='Stop simulated'):
            call()
    assert not model.debug.exists()


def test_later_config_edit_survives_rollback(model):
    trial = trial_install(model)
    main = model.base.path(tool.MAIN)
    main.write_bytes(main.read_bytes() + b'# later user config\n')
    trial.rollback()
    model.cold_boot()
    assert b'# later user config' in main.read_bytes()
    assert tool.BLOCK not in main.read_bytes()


def test_loss_of_debug_only_reproduces_missing_module_failure(model):
    trial_install(model)
    model.firmware_reset(clear_prepared=False)
    assert not model.cold_boot()['loadable']


def test_actual_first_update_marker_removal_restores_config_before_module_loss(model):
    trial_install(model)
    # Observed vendor order: remove .printer_data, then remove .debug.
    model.firmware_reset(clear_debug=False, clear_prepared=True)
    result = model.cold_boot()
    assert result == {'system_layer_cleared': False, 'origin_config_restored': True, 'loadable': True}
    assert model.debug.exists() and model.base.path(tool.TARGETS[0]).exists()
    assert tool.BLOCK not in model.base.path(tool.MAIN).read_bytes()


def test_disabled_user_config_mode_restores_origin_even_without_update(model):
    model.base.install()
    model.fluidd.unlink()
    result = model.cold_boot()
    assert result['loadable'] and result['origin_config_restored']
    assert tool.BLOCK not in model.base.path(tool.MAIN).read_bytes()


def test_full_vendor_marker_reset_restores_stock_config(model):
    trial_install(model)
    model.firmware_reset()
    assert model.cold_boot() == {'system_layer_cleared': True, 'origin_config_restored': True, 'loadable': True}
    assert tool.BLOCK not in model.base.path(tool.MAIN).read_bytes()
    # The orphan cfg survives, so an external wildcard include would be unsafe.
    assert model.base.path(tool.TARGETS[1]).exists()


@pytest.mark.parametrize('clear_prepared', [False, True])
def test_explicit_pre_update_rollback_survives_both_resets(model, clear_prepared):
    trial = trial_install(model)
    assert trial.prepare_update() == 'stock-before-update'
    model.firmware_reset(clear_prepared=clear_prepared)
    assert model.cold_boot()['loadable']
    assert not any(model.base.path(p).exists() for p in tool.TARGETS[:2])


def test_corrupt_persistence_record_never_triggers_cleanup(model):
    trial = trial_install(model)
    data = json.loads(trial.record.read_text())
    data['debug_before'] = tool.encode(b'other')
    trial.record.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Corrupt'):
        trial.rollback()
    assert model.debug.exists() and model.loadable()
    assert tool.BLOCK in model.base.path(tool.MAIN).read_bytes()


def test_modified_owned_module_is_not_removed(model):
    trial = trial_install(model)
    p = model.base.path(tool.TARGETS[0])
    p.write_bytes(p.read_bytes() + b'\n# user change\n')
    with pytest.raises(ValueError, match='Owned file changed'):
        trial.rollback()
    assert b'# user change' in p.read_bytes() and model.debug.exists()


def test_retry_install_requires_recovery_instead_of_overwrite(model):
    trial = PersistenceTrial(model)
    plan = trial.plan()
    with pytest.raises(RuntimeError):
        trial.install(plan, accept_whole_overlay=True, fail_after=2)
    with pytest.raises(ValueError, match='already exists'):
        trial.install(plan, accept_whole_overlay=True)
    trial.rollback()
    trial.install(trial.plan(), accept_whole_overlay=True)
    assert model.cold_boot()['loadable']
