import os
import subprocess
import sys
from pathlib import Path
import pytest
from tracker_uid_catalog import UidCatalog
from tracker_uid_window import UidWindow


def test_writer_lock_is_cross_process_even_for_unmigrated_database(tmp_path):
    path = tmp_path/'new.sqlite'
    catalog = UidCatalog(path)
    catalog.register_manual('Preserved', 123456)
    script = 'from tracker_uid_catalog import UidCatalog; UidCatalog(__import__("sys").argv[1])'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    try:
        child = subprocess.run([sys.executable, '-c', script, str(path)], env=env, capture_output=True)
        assert child.returncode != 0
        assert 'База занята' in child.stderr.decode()
        assert catalog.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0] == 123456
    finally:
        catalog.close()
    reopened = UidCatalog(path)
    reopened.close()


def test_failed_open_releases_writer_lock(tmp_path):
    path = tmp_path/'bad.sqlite'
    path.write_bytes(b'invalid database')
    for _ in range(2):
        with pytest.raises(Exception) as exc:
            UidCatalog(path)
        assert 'База занята' not in str(exc.value)


class Event:
    def __iadd__(self, handler): self.handler=handler; return self


def test_close_hides_and_quit_destroys_without_js_native_references(tmp_path):
    from types import SimpleNamespace
    from threading import Event as Signal
    hidden=Signal();calls=[]
    window=SimpleNamespace(events=SimpleNamespace(shown=Event(), closing=Event()),
        hide=hidden.set, show=lambda:calls.append('show'), restore=lambda:calls.append('restore'),
        destroy=lambda:calls.append('destroy'))
    def create(*args, **kwargs):
        assert 'js_api' not in kwargs
        return window
    shell=UidWindow('http://127.0.0.1:12345',tmp_path,webview_module=SimpleNamespace(create_window=create))
    shell.show();window.events.shown.handler()
    assert 'show' in calls
    assert window.events.closing.handler() is False
    assert hidden.wait(2)
    shell.show();shell.quit()
    assert window.events.closing.handler() is True
    assert calls[-1]=='destroy'
