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


def test_single_window_show_hide_reopen_and_quit():
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
        "name": "Black", "material": "PLA", "remaining_g": 960}}))
    store.update(lambda db: db["slots"].__setitem__("1", "one"))
    monkeypatch.setattr(spool_tracker, "STORE", store)
    controller = SimpleNamespace(shows=0, quits=0)
    controller.show = lambda: setattr(controller, "shows", controller.shows + 1)
    controller.quit = lambda: setattr(controller, "quits", controller.quits + 1)
    app = spool_tracker.TrayApp()
    app.window_controller = controller
    items = [item for item in app.build_menu() if isinstance(item, MenuItem)]
    assert all(item.enabled for item in items)
    assert "Black — 960g" in items[1].text
    for item in items[:-1]:
        item.action(None, item)
    assert controller.shows == 6  # title, four rows, Configure
    items[-1].action(None, items[-1])
    assert controller.quits == 1


def test_hook_mode_never_creates_dashboard(monkeypatch):
    monkeypatch.setattr(spool_tracker, "configure_logging", lambda: None)
    monkeypatch.setattr(spool_tracker, "handle_slicer_hook", lambda path: 7)
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: 1 / 0)
    monkeypatch.setattr(spool_tracker.sys, "argv", ["spool_tracker.py", "job.gcode"])
    assert spool_tracker.main() == 7


def test_second_tray_launch_exits_without_creating_gui(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.read()
    monkeypatch.setattr(spool_tracker, "STORE", store)
    monkeypatch.setattr(spool_tracker, "ThreadingHTTPServer", lambda *args: (_ for _ in ()).throw(OSError(48, "busy")))
    monkeypatch.setattr(spool_tracker.TrayApp, "_activate_existing", staticmethod(lambda: True))
    monkeypatch.setattr(spool_tracker, "DashboardWindow", lambda: 1 / 0)
    assert spool_tracker.TrayApp().run() == 0
