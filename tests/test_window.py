import sys
import threading
from types import SimpleNamespace

import spool_tracker
from storage import Store


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return [handler() for handler in self.handlers]


class FakeWindow:
    def __init__(self):
        self.events = SimpleNamespace(shown=FakeEvent(), closing=FakeEvent())
        self.calls = []
        self.hidden = threading.Event()

    def show(self):
        self.calls.append("show")

    def restore(self):
        self.calls.append("restore")

    def hide(self):
        self.calls.append("hide")
        self.hidden.set()

    def destroy(self):
        self.calls.append("destroy")


def test_single_window_show_hide_reopen_and_quit(monkeypatch):
    monkeypatch.setattr(spool_tracker.sys, "platform", "win32")
    window = FakeWindow()
    webview = SimpleNamespace(create_window=lambda *args, **kwargs: window,
                              start=lambda: window.calls.append("start"))
    controller = spool_tracker.DashboardWindow(webview)
    controller.show()  # A tray click before the GUI loop is ready is remembered.
    assert window.calls == []
    window.events.shown.fire()
    assert window.calls == ["show", "restore"]
    assert window.events.closing.fire() == [False]
    assert window.hidden.wait(2)
    controller.show()
    assert window.calls[-2:] == ["show", "restore"]
    controller.run()
    controller.quit()
    assert window.calls[-2:] == ["start", "destroy"]
    assert window.events.closing.fire() == [True]
    controller.show()
    assert window.calls[-1] == "destroy"


def test_tray_information_rows_are_actionable_and_open_dashboard(tmp_path, monkeypatch):
    class MenuItem:
        def __init__(self, text, action, **kwargs):
            self.text, self.action = text, action
            self.enabled = kwargs.get("enabled", True)

    class Menu(tuple):
        SEPARATOR = object()

        def __new__(cls, *items):
            return super().__new__(cls, items)

    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(MenuItem=MenuItem, Menu=Menu))
    store = Store(tmp_path)
    store.read()
    store.update(lambda db: db["spools"].update({"one": {
        "name": "Black", "material": "PLA", "remaining_g": 960, "color": "#121619"}}))
    store.update(lambda db: db["slots"].__setitem__("1", "one"))
    monkeypatch.setattr(spool_tracker, "STORE", store)
    controller = SimpleNamespace(shows=0, quits=0)
    controller.show = lambda: setattr(controller, "shows", controller.shows + 1)
    controller.quit = lambda: setattr(controller, "quits", controller.quits + 1)
    app = spool_tracker.TrayApp()
    app.window_controller = controller
    items = [item for item in app.build_menu() if isinstance(item, MenuItem)]
    assert all(item.enabled for item in items)
    assert "T0 · Black — 960 g" in items[1].text
    assert items[1]._tracker_toolhead is True
    assert items[1]._tracker_color == '#121619'
    assert [item.text.split(' · ')[0] for item in items[1:5]] == ['T0', 'T1', 'T2', 'T3']
    for item in items[:-1]:
        item.action(None, item)
    assert controller.shows == 6  # title, four rows, Configure
    items[-1].action(None, items[-1])
    assert controller.quits == 1


def test_native_menu_decorates_only_toolheads(monkeypatch):
    class NativeImage:
        def alloc(self): return self
        def initWithData_(self, data): self.data = data; return self
        def setSize_(self, size): self.size = size
        def setTemplate_(self, template): self.template = template
    class NativeData:
        @staticmethod
        def dataWithBytes_length_(data, length): return data[:length]
    class NativeItem:
        def __init__(self): self.image = None
        def setImage_(self, image): self.image = image
    class Icon:
        def _create_menu_item(self, descriptor, callbacks): return NativeItem()
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(NSImage=NativeImage()))
    monkeypatch.setitem(sys.modules, 'Foundation', SimpleNamespace(NSData=NativeData))
    icon = Icon()
    spool_tracker.install_macos_toolhead_icons(icon)
    item = icon._create_menu_item(SimpleNamespace(_tracker_toolhead=True, _tracker_color='#f09422'), [])
    assert item.image is not None and item.image.size == (18, 22)
    assert item.image.data.startswith(b'\x89PNG')
    assert icon._create_menu_item(SimpleNamespace(), []).image is None


def test_hook_mode_never_creates_dashboard(monkeypatch):
    monkeypatch.setattr(spool_tracker, "configure_logging", lambda: None)
    monkeypatch.setattr(spool_tracker, "handle_slicer_hook", lambda path: 7)
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: 1 / 0)
    monkeypatch.setattr(spool_tracker.sys, "argv", ["spool_tracker.py", "job.gcode"])
    assert spool_tracker.main() == 7


def test_package_self_test_does_not_touch_data_or_open_gui(monkeypatch):
    monkeypatch.setattr(spool_tracker.sys, "argv", ["spool_tracker.py", "--self-test"])
    monkeypatch.setattr(spool_tracker, "configure_logging", lambda: 1 / 0)
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: 1 / 0)
    assert spool_tracker.main() == 0


def test_native_guard_alert_describes_actual_pause(monkeypatch):
    calls = []
    monkeypatch.setattr(spool_tracker, "show_dialog", lambda message, lang: calls.append((message, lang)))
    spool_tracker.TrayApp._notify_guard({"language": "ru", "last_guard": {
        "filename": "test.gcode", "state": "paused"}})
    assert len(calls) == 1
    assert "test.gcode" in calls[0][0]
    assert "поставил печать на паузу" in calls[0][0]
    assert calls[0][1] == "ru"


def test_second_tray_launch_exits_without_creating_gui(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.read()
    monkeypatch.setattr(spool_tracker, "STORE", store)
    monkeypatch.setattr(spool_tracker, "ThreadingHTTPServer", lambda *args: (_ for _ in ()).throw(OSError(48, "busy")))
    monkeypatch.setattr(spool_tracker.TrayApp, "_activate_existing", staticmethod(lambda: True))
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: 1 / 0)
    assert spool_tracker.TrayApp().run() == 0


def test_busy_worker_lock_exits_before_gui_and_monitoring(tmp_path, monkeypatch):
    from filelock import FileLock, Timeout
    import pytest
    store = Store(tmp_path / "inventory", legacy_paths=())
    store.read()
    monkeypatch.setattr(spool_tracker, "STORE", store)
    monkeypatch.setattr(spool_tracker, "ISOLATED_ROOT", None)
    calls = []
    server = SimpleNamespace(server_port=8766, server_close=lambda: calls.append("closed"))
    monkeypatch.setattr(spool_tracker, "ThreadingHTTPServer", lambda *args: server)
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: pytest.fail("GUI started"))
    monkeypatch.setattr(spool_tracker, "show_dialog", lambda message, lang: calls.append(message))
    app = spool_tracker.TrayApp()
    monkeypatch.setattr(app.monitor, "start", lambda: pytest.fail("Printer monitoring started"))
    monkeypatch.setattr(app.motion_diagnostic, "start", lambda: pytest.fail("Motion recorder started"))
    lock_path = str(store.directory / "spoolman-worker.lock")
    owner = FileLock(lock_path, timeout=0)
    contender = FileLock(lock_path, timeout=0)
    before = store.read()
    with owner:
        assert app.run() == 1
        assert calls[-1] == "closed"
        assert len(calls) == 2
        assert "Tracker" in calls[0]
        assert app.spoolman_bridge.thread is None
        assert store.read() == before
        with pytest.raises(Timeout):
            contender.acquire()
    # Exiting the rejected instance must not damage the lock or prevent restart.
    with contender:
        assert contender.is_locked


def test_webview_injection_exposes_only_backup_actions(monkeypatch):
    import json
    import webview.util
    scripts = []
    inspected_handles = []
    class InternalHandle:
        def __dir__(self):
            inspected_handles.append(self)
            return []
    bridge = spool_tracker.BackupBridge(InternalHandle(), InternalHandle())
    bridge._window = InternalHandle()
    loaded = threading.Event()
    window = SimpleNamespace(
        _js_api=bridge, _functions={}, _expose_lock=threading.Lock(),
        run_js=scripts.append,
        events=SimpleNamespace(before_load=threading.Event(),
                               _pywebviewready=threading.Event(), loaded=loaded))
    monkeypatch.setattr(webview.util, 'load_js_files', lambda *args: ('bootstrap', '%(functions)s'))
    webview.util.inject_pywebview('edgechromium', window)
    assert loaded.wait(3), 'JS API initialization did not finish'
    assert window.events._pywebviewready.is_set()
    assert inspected_handles == [], "Native handles leaked into JS API inspection"
    functions = json.loads(scripts[-1])
    assert {row['func'] for row in functions} == {'hide', 'export_backup', 'import_backup'}
