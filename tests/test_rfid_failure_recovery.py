"""Recovery must turn activation off even if its diagnostic writes fail."""
import errno
from pathlib import Path
import sys
import pytest
from test_rfid_u1_trial import trial
from scripts import rfid_u1_trial as tool

@pytest.mark.parametrize('failure',[errno.ENOSPC,errno.EACCES,errno.EROFS])
def test_disable_removes_activation_when_recovery_writes_fail(trial,monkeypatch,failure):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    before=t.path(tool.MAIN).read_bytes()
    def fail(*a,**k):raise OSError(failure,'injected recovery write failure')
    monkeypatch.setattr(tool,'atomic',fail)
    result=t.disable()
    assert result['state']=='disabled' and result['warnings']
    assert not t.path(tool.CFG).exists()
    assert t.path(tool.MAIN).read_bytes()==before


def test_real_readonly_recovery_directory_does_not_prevent_off(trial):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    recovery=t.path(tool.RECOVERY);recovery.chmod(0o500)
    try:
        result=t.disable()
        assert result['state']=='disabled' and result['warnings']
        assert not t.path(tool.CFG).exists()
    finally:recovery.chmod(0o700)


def test_readonly_activation_directory_reports_failure_without_false_success(trial):
    t,module=trial;t.install(t.plan(module,['bambu']),module)
    parent=t.path(tool.CFG).parent;parent.chmod(0o500)
    try:
        with pytest.raises(PermissionError):t.disable()
        assert t.path(tool.CFG).exists()
    finally:parent.chmod(0o755)
