import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.rfid_u1_trial import Trial, MAIN, MODULE, DRIVER, CFG, RECOVERY, BLOCK, AUTOSAVE, digest

pytestmark=pytest.mark.skipif(sys.platform=='win32',reason='POSIX offline installation')


@pytest.fixture
def trial(tmp_path,monkeypatch):
    root=tmp_path.resolve()/'offline-u1'
    for name in (DRIVER,MAIN):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    driver=b'# synthetic stock driver\n'
    monkeypatch.setattr('scripts.rfid_u1_trial.APPROVED_DRIVER',digest(driver))
    (root/DRIVER).write_bytes(driver)
    (root/MAIN).write_bytes(b'[printer]\nkinematics: none\n'+AUTOSAVE+b'\n#*# [probe]\n#*# z_offset = 1.25\n')
    module=tmp_path/'module.py'
    module.write_text('SUPPORTED_DRIVERS = '+repr({digest(driver):'fixture'})+'\n')
    return Trial(root),module


def test_install_disable_rollback_preserves_later_calibration(trial):
    t,module=trial;before=t.path(MAIN).read_bytes();driver=t.path(DRIVER).read_bytes()
    p=t.plan(module,['bambu']);t.install(p,module)
    assert t.path(MAIN).read_bytes().index(BLOCK)<t.path(MAIN).read_bytes().index(AUTOSAVE)
    assert not (t.root/'oem/.debug').exists()
    t.path(MAIN).write_bytes(t.path(MAIN).read_bytes().replace(b'1.25',b'1.42'))
    t.path(MODULE).write_bytes(b'def load_config(:\n')
    # Run only the installed standalone copy, no source checkout import needed.
    cli=t.path(RECOVERY+'/rfid_u1_trial.py')
    for action in ('disable','disable','rollback','rollback'):
        result=subprocess.run([sys.executable,'-I',str(cli),action,'--offline-root',str(t.root)],cwd=t.root,capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stdout+result.stderr
    assert t.path(MAIN).read_bytes()==before.replace(b'1.25',b'1.42')
    assert t.path(DRIVER).read_bytes()==driver
    assert t.path(RECOVERY+'/retained-module.py').read_bytes()==b'def load_config(:\n'
    assert not t.path(MODULE).exists() and not t.path(CFG).exists()


@pytest.mark.parametrize('boundary',range(3))
def test_interrupted_install_recoverable(trial,boundary):
    t,module=trial;before=t.path(MAIN).read_bytes()
    with pytest.raises(RuntimeError):t.install(t.plan(module,['bambu']),module,fail_after=boundary)
    assert not t.path(CFG).exists()
    assert t.rollback()['state']=='rolled-back'
    assert t.path(MAIN).read_bytes()==before and not t.path(MODULE).exists()


@pytest.mark.parametrize('boundary',range(2))
def test_interrupted_rollback_never_reenables(trial,boundary):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    with pytest.raises(RuntimeError):t.rollback(fail_after=boundary)
    assert not t.path(CFG).exists()
    t.rollback();assert BLOCK not in t.path(MAIN).read_bytes()


@pytest.mark.parametrize('change',['driver','config','module','include'])
def test_stale_plan_never_writes(trial,change):
    t,module=trial
    included=t.path(MAIN).with_name('other.cfg');included.write_bytes(b'# original\n')
    t.path(MAIN).write_bytes(b'[include other.cfg]\n'+t.path(MAIN).read_bytes())
    plan=t.plan(module,['bambu'])
    p={'driver':t.path(DRIVER),'config':t.path(MAIN),'module':module,'include':included}[change]
    p.write_bytes(p.read_bytes()+b'\n# changed\n')
    with pytest.raises(ValueError):t.install(plan,module)
    assert not t.path(RECOVERY).exists() and not t.path(CFG).exists()


def test_edited_include_is_disabled_but_not_overwritten(trial):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    edited=t.path(MAIN).read_bytes().replace(b'END TRACKER RFID TRIAL',b'END TRACKER RFID TRIAL edited')
    t.path(MAIN).write_bytes(edited)
    with pytest.raises(ValueError):t.rollback()
    assert t.path(MAIN).read_bytes()==edited and not t.path(CFG).exists()


def test_real_root_links_and_unknown_driver_rejected(trial,tmp_path):
    with pytest.raises(ValueError):Trial('/')
    t,module=trial
    t.path(DRIVER).write_bytes(b'unknown')
    with pytest.raises(ValueError):t.plan(module,['bambu'])
    t.path(DRIVER).unlink();t.path(DRIVER).symlink_to(module)
    with pytest.raises(ValueError):t.plan(module,['bambu'])


def test_stock_overlay_cleanup_leaves_optional_include(trial):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    t.path(MODULE).unlink();t.path(CFG).unlink()
    assert BLOCK in t.path(MAIN).read_bytes()
    t.disable();t.rollback()
    assert BLOCK not in t.path(MAIN).read_bytes()


def test_existing_persistence_is_not_silently_accepted(trial):
    t,module=trial
    t.path('oem').mkdir();t.path('oem/.debug').write_bytes(b'user-owned')
    with pytest.raises(ValueError,match='one-boot'):t.plan(module,['bambu'])
    assert t.path('oem/.debug').read_bytes()==b'user-owned'


def test_preexisting_wildcard_cannot_load_trial_twice(trial):
    t,module=trial
    t.path(MAIN).write_bytes(b'[include ../../klipper/klippy/extras/*.cfg]\n'+t.path(MAIN).read_bytes())
    with pytest.raises(ValueError,match='twice'):t.plan(module,['bambu'])
    assert not t.path(CFG).exists()
