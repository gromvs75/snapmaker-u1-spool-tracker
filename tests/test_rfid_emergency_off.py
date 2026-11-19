"""Independent OFF switch against failed/corrupt module installations."""
import json
import subprocess
import sys

import pytest

from dev.klipper.disable_rfid import disable
from dev.labs.uid_boot_bench.debug_loader import KIT, SERVICE
from dev.labs.uid_boot_bench.optional import CFG
from dev.labs.uid_boot_bench.selective import ENABLED
from tests.test_rfid_debug_loader import model, install, dispatch

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX recovery bench')


@pytest.mark.parametrize('damage', ['syntax', 'missing', 'configuration'])
def test_independent_off_with_running_error_process_and_broken_module(model, damage):
    install(model).activate()
    module = model.base.path('klipper/klippy/extras/tracker_uid.py')
    if damage == 'missing':
        module.unlink()
    elif damage == 'syntax':
        module.write_bytes(b'this is invalid Python !\n')
    else:
        model.base.path(CFG).write_bytes(b'[tracker_uid]\nenabled: invalid\n')
    main = model.base.path('printer_data/config/printer.cfg').read_bytes()
    cfg = model.base.path(CFG).read_bytes()
    model.base.path('.klipper-running').touch()  # OFF is allowed even in error state.
    command = [sys.executable, '-I', str(model.base.path(KIT + '/disable-rfid.py')),
               '--simulator-root', str(model.root)]
    result = json.loads(subprocess.check_output(command, text=True))
    assert result['state'] == 'disabled' and result['effective'] == 'next-klipper-start'
    assert model.base.path(result['saved_config']).read_bytes() == cfg
    assert not model.base.path(CFG).exists() and not model.base.path(ENABLED).exists()
    assert model.base.path('printer_data/config/printer.cfg').read_bytes() == main
    assert model.debug.exists()
    assert json.loads(subprocess.check_output(command, text=True))['saved_config'] is None
    model.base.path('.klipper-running').unlink()
    for _ in range(2):
        model.cold_boot()
        result = dispatch(model)
        assert result.returncode == 0, result.stderr + result.stdout
        assert 'STOCK_START:start' in result.stdout
        assert not model.base.path(CFG).exists()


@pytest.mark.parametrize('boundary', [0, 1])
def test_interrupted_off_is_retryable_and_never_enables_module(model, boundary):
    install(model).activate()
    with pytest.raises(RuntimeError, match='Interrupted'):
        disable(model.root, fail_after=boundary)
    assert not model.base.path(ENABLED).exists()
    assert disable(model.root)['state'] == 'disabled'
    assert dispatch(model).returncode == 0
    assert not model.base.path(CFG).exists()


@pytest.mark.parametrize('lock_name', ['persistent/tracker-deployment/debug-loader.lock',
                                       '.tracker-uid-install.lock'])
def test_off_does_not_race_activation_or_rollback(model, lock_name):
    import fcntl
    install(model).activate()
    with model.base.path(lock_name).open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            disable(model.root)
        assert model.base.path(CFG).exists() and model.base.path(ENABLED).exists()


def test_off_rejects_unowned_configuration_without_mutation(model):
    install(model).activate()
    model.base.path('printer_data/config/printer.cfg').write_bytes(b'[printer]\n')
    with pytest.raises(ValueError, match='include changed'):
        disable(model.root)
    assert model.base.path(CFG).exists() and model.base.path(ENABLED).exists()


def test_off_rejects_symlink_without_mutation(model, tmp_path):
    install(model).activate()
    cfg = model.base.path(CFG)
    cfg.unlink()
    foreign = tmp_path / 'unrelated.cfg'
    foreign.write_bytes(b'keep')
    cfg.symlink_to(foreign)
    with pytest.raises(ValueError, match='Symlink'):
        disable(model.root)
    assert foreign.read_bytes() == b'keep' and model.base.path(ENABLED).exists()
