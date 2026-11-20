import sys
from types import SimpleNamespace

import pytest

from tracker_uid_window import UidWindow


@pytest.mark.parametrize('visible,minimized,active,ready,quitting,expected', [
    (True, False, True, True, False, False),
    (True, False, False, True, False, True),
    (False, False, True, True, False, True),
    (True, True, True, True, False, True),
    (True, False, False, False, False, False),
    (False, False, False, True, True, False),
])
def test_automatic_menu_checks_macos_focus(monkeypatch, visible, minimized, active, ready, quitting, expected):
    app = SimpleNamespace(isActive=lambda: active)
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: app)))
    shell = object.__new__(UidWindow)
    shell._ready, shell._quitting = ready, quitting
    shell._window = SimpleNamespace(native=SimpleNamespace(
        isVisible=lambda: visible, isMiniaturized=lambda: minimized))
    assert shell._can_popup_forecast() is expected
    shell._window.native = None
    assert shell._can_popup_forecast() is False


@pytest.mark.parametrize('visible,active,queued,expected_popup', [
    (False, True, False, True),
    (True, True, False, False),
    (True, False, False, True),
    (True, False, True, True),
    (True, True, True, False),
])
def test_only_new_slice_opens_menu_when_tracker_is_in_background(monkeypatch, visible, active, queued, expected_popup):
    import tracker_user_tray
    monkeypatch.setattr(sys, 'platform', 'darwin')
    callbacks, clicks, updates = [], [], []
    def schedule(callback, *args):
        if queued:
            callbacks.append(lambda: callback(*args))
        else:
            callback(*args)
    monkeypatch.setitem(sys.modules, 'PyObjCTools', SimpleNamespace(
        AppHelper=SimpleNamespace(callAfter=schedule)))
    app = SimpleNamespace(active=not active if queued else active)
    app.isActive = lambda: app.active
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: app)))
    monkeypatch.setattr(tracker_user_tray, 'tray_model', lambda snapshot: snapshot)
    monkeypatch.setattr(tracker_user_tray, 'create_tray_icon', lambda status: status)
    def menu(model, *actions):
        updates.append(model)
        return model
    monkeypatch.setattr(tracker_user_tray, 'build_menu', menu)
    models = [dict(status='pending', event=None),
              dict(status='ok', event=('old', 90, 'hash')),
              dict(status='shortage', event=('old', 90, 'hash')),
              dict(status='ok', event=('new', 120, 'hash-2')),
              dict(status='ok', event=('new', 120, 'hash-2')),
              dict(status='shortage', event=('new', 120, 'hash-2'))]
    shell = object.__new__(UidWindow)
    shell._started_at_ns = 100
    shell._ready, shell._quitting, shell._menu_presented = True, False, False
    shell._forecast = SimpleNamespace(snapshot=lambda: models.pop(0))
    shell._tray_stop = SimpleNamespace(is_set=lambda: not models, wait=lambda seconds: None)
    native = SimpleNamespace(isVisible=lambda: visible, isMiniaturized=lambda: False)
    shell._window = SimpleNamespace(native=native)
    tray = SimpleNamespace(_status_item=SimpleNamespace(button=lambda: SimpleNamespace(
        performClick_=lambda sender: clicks.append(tray.menu['event']))))
    shell._watch_forecast(tray)
    # The user can switch between Tracker and Orca while callbacks are queued.
    app.active = active
    for callback in callbacks:
        callback()
    assert clicks == ([('new', 120, 'hash-2')] if expected_popup else [])
    assert len(updates) == 5  # repeated telemetry is not another notification
    assert tray.icon == 'shortage'
    assert not shell._menu_presented
