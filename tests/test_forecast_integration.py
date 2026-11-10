import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from storage import Store
from forecast_service import ForecastService
from dev.observer_fixture import payload
import spool_tracker


def test_service_partial_reslice_multiple_plates_restart_without_debit(tmp_path):
    store = Store(tmp_path / 'inventory', legacy_paths=())
    store.read()
    before = store.path.read_bytes()
    shown = []
    root = tmp_path / 'slices'
    service = ForecastService(store, lambda: shown.append(True), root)
    assert service.poll() == []
    assert not root.exists()
    folder = root / 'date/session/Metadata'
    folder.mkdir(parents=True)
    one = folder / '.42.0.gcode'
    one.write_bytes(payload()[:-20])
    service.poll(); service.observer.settle = 0
    assert service.poll() == [] and shown == []
    one.write_bytes(payload('3, 0, 0, 0'))
    service.poll(); service.poll()
    assert len(shown) == 1
    two = folder / '.42.1.gcode'
    two.write_bytes(payload('4, 0, 0, 0'))
    one.write_bytes(payload('5, 0, 0, 0'))
    service.poll(); service.poll()
    assert len(shown) == 2
    assert len(service.snapshot()['entries']) == 2
    assert {e['weights'][0] for e in service.snapshot()['entries']} == {4, 5}
    service.poll(); assert len(shown) == 2
    restarted = ForecastService(store, lambda: None, root)
    restarted.poll(); restarted.observer.settle = 0; restarted.poll()
    assert len(restarted.snapshot()['entries']) == 2
    assert store.path.read_bytes() == before


def test_isolated_runtime_never_imports_installed_store(tmp_path, monkeypatch):
    for name in ('STORE', 'WEB_PORT', 'ISOLATED_ROOT', 'SLICE_ROOT'):
        monkeypatch.setattr(spool_tracker, name, getattr(spool_tracker, name))
    (tmp_path / 'ISOLATED_TRACKER_TEST').write_text('offline-only\n')
    spool_tracker.configure_runtime(['--isolated-root', str(tmp_path)])
    assert spool_tracker.STORE.directory == tmp_path / 'inventory'
    assert spool_tracker.WEB_PORT == 0
    assert not spool_tracker.STORE.read()['printer']['enabled']
    with pytest.raises(SystemExit):
        spool_tracker.configure_runtime(['--isolated-root', str(tmp_path), '--slice-root', str(tmp_path.parent)])


def test_forecast_popup_queued_until_window_loaded(monkeypatch):
    from tests.test_window import FakeWindow
    w = FakeWindow(); w.evaluate_js = lambda script: w.calls.append(script)
    view = SimpleNamespace(create_window=lambda *a, **k: w)
    monkeypatch.setattr(spool_tracker.sys, 'platform', 'win32')
    controller = spool_tracker.DashboardWindow(view)
    controller.show_forecast()
    assert w.calls == []
    controller._on_loaded()
    assert w.calls[:2] == ['show', 'restore']
    assert 'refreshSliceForecast' in w.calls[2]
    controller.quit(); before = list(w.calls); controller.show_forecast()
    assert w.calls == before


def test_active_print_forecast_snapshot_does_not_replace_accounting(tmp_path):
    store = Store(tmp_path, legacy_paths=())
    store.update(lambda db: db['monitor'].update(state='printing'))
    before = store.path.read_bytes()
    assert ForecastService(store, lambda: None, tmp_path).snapshot()['printing']
    assert store.path.read_bytes() == before


def test_cross_platform_reader_without_posix_flags(tmp_path, monkeypatch):
    import slice_observer
    p = tmp_path / 'slice.gcode'; p.write_bytes(payload())
    monkeypatch.delattr(slice_observer.os, 'O_NOFOLLOW', raising=False)
    monkeypatch.delattr(slice_observer.os, 'O_NONBLOCK', raising=False)
    assert slice_observer.read_snapshot(p)[0] == payload()


@pytest.mark.parametrize('method,path', [('GET','/api/printer/tags'), ('POST','/api/printer/test'), ('POST','/api/printer/config'), ('POST','/api/guard/decision'), ('POST','/api/sender/start'), ('POST','/api/accounting/reconcile')])
def test_isolated_handler_rejects_network_and_accounting_routes(method, path):
    handler = object.__new__(spool_tracker.WebHandler)
    handler.isolated = True
    handler.path = path
    handler._allowed_host = lambda: True
    calls = []
    handler._response = lambda status, body: calls.append(status)
    getattr(handler, 'do_' + method)()
    assert calls == [403]


def test_main_backup_bridge_restore_and_export_offline(tmp_path, monkeypatch):
    from backup import create_backup, parse_backup
    store = Store(tmp_path / 'inventory', legacy_paths=())
    source = tmp_path / 'backup.json'
    doc = create_backup(store, '1.1.0-beta.1')
    doc['data']['spools'] = {'s': {'name':'Test', 'material':'PLA', 'remaining_g':77.5}}
    doc['data']['slots']['1'] = 's'
    doc['data']['printer']['enabled'] = True
    source.write_text(json.dumps(doc))
    module = SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1, SAVE=2))
    bridge = spool_tracker.BackupBridge(store, module)
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: [str(source)])
    monkeypatch.setattr(spool_tracker, 'ISOLATED_ROOT', tmp_path)
    assert bridge.import_backup()['status'] == 'ok'
    assert store.read()['spools']['s']['remaining_g'] == 77.5
    assert store.read()['slots']['1'] == 's'
    assert not store.read()['printer']['enabled']
    out = tmp_path / 'roundtrip.json'
    bridge._window.create_file_dialog = lambda *a, **k: str(out)
    assert bridge.export_backup()['status'] == 'ok'
    assert parse_backup(out)['spools'] == store.read()['spools']


def test_tray_status_tracks_inventory_and_missing_evidence(tmp_path, monkeypatch):
    store = Store(tmp_path / 'inventory', legacy_paths=())
    def seed(db):
        db['spools']['one'] = {'name': 'Test PLA', 'material': 'PLA', 'remaining_g': 30}
        db['slots']['1'] = 'one'
        db['safety_margin_g'] = 5
    store.update(seed)
    monkeypatch.setattr(spool_tracker, 'STORE', store)
    app = spool_tracker.TrayApp()
    app.window_controller = SimpleNamespace(show=lambda: pytest.fail('Unexpected window'),
                                            show_forecast=lambda: pytest.fail('Unexpected forecast window'))
    notices = []
    service = ForecastService(store, lambda: notices.append(True), tmp_path / 'slices')
    app.forecast_service = service
    assert app._forecast_status(service.snapshot())[0] == 'unknown'
    folder = service.root / 'session/Metadata'
    folder.mkdir(parents=True)
    (folder / '.1.0.gcode').write_bytes(payload('20, 0, 0, 0'))
    service.poll(); service.observer.settle = 0; service.poll()
    assert notices == [True]
    assert service.snapshot()['auto_shows'] == 0
    assert app._forecast_status(service.snapshot())[0] == 'ok'
    store.update(lambda db: db['spools']['one'].update(remaining_g=24))
    assert app._forecast_status(service.snapshot())[0] == 'shortage'
    store.update(lambda db: db['slots'].__setitem__('1', ''))
    assert app._forecast_status(service.snapshot())[0] == 'unknown'
    service.state.error = 'Observer unavailable'
    assert app._forecast_status(service.snapshot())[0] == 'unknown'


def test_macos_accessory_policy_applied_after_cocoa_import(monkeypatch):
    import sys
    from tests.test_window import FakeWindow
    from types import ModuleType
    calls = []
    appkit = SimpleNamespace(NSApplicationActivationPolicyAccessory=1,
                            NSApplication=SimpleNamespace(sharedApplication=lambda: SimpleNamespace(
                                setActivationPolicy_=lambda value: calls.append(('policy', value)))))
    platforms = ModuleType('webview.platforms')
    platforms.cocoa = object()
    monkeypatch.setattr('macos_menu.configure_accessory_panel', lambda cocoa: None)
    monkeypatch.setitem(sys.modules, 'webview.platforms', platforms)
    monkeypatch.setitem(sys.modules, 'AppKit', appkit)
    monkeypatch.setattr(spool_tracker.sys, 'platform', 'darwin')
    monkeypatch.setattr(spool_tracker, 'ISOLATED_ROOT', None)
    controller = spool_tracker.DashboardWindow(SimpleNamespace(
        create_window=lambda *a, **k: FakeWindow(), start=lambda: calls.append(('start',))))
    controller.run()
    assert calls == [('policy', 1), ('start',)]


def test_forecast_menu_click_does_not_evaluate_js_on_gui_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(spool_tracker, "STORE", Store(tmp_path, legacy_paths=()))
    import threading
    app = spool_tracker.TrayApp()
    called = threading.Event()
    threads = []
    def reveal():
        threads.append(threading.current_thread())
        called.set()
    app.window_controller = SimpleNamespace(show_forecast=reveal)
    app._open_forecast()
    assert called.wait(2)
    assert threads[0] is not threading.current_thread()


def test_slice_opens_native_menu_on_main_thread_without_dashboard(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(spool_tracker, 'STORE', Store(tmp_path, legacy_paths=()))
    monkeypatch.setattr(spool_tracker.sys, 'platform', 'darwin')
    queued, calls = [], []
    monkeypatch.setitem(sys.modules, 'PyObjCTools', SimpleNamespace(
        AppHelper=SimpleNamespace(callAfter=lambda callback: queued.append(callback))))
    app = spool_tracker.TrayApp()
    app.window_controller = SimpleNamespace(show_forecast=lambda: pytest.fail('Dashboard opened'))
    def click(sender):
        calls.append('popup')
        app._show_slice_menu()  # A reentrant event must not open a second menu.
        app._refresh_menu()  # Do not replace the menu while AppKit is tracking it.
    app.icon = SimpleNamespace(visible=False, _status_item=SimpleNamespace(
        button=lambda: SimpleNamespace(performClick_=click)))
    monkeypatch.setattr(app, 'build_menu', lambda snapshot=None: calls.append('refresh'))
    app._on_slice_completed()
    assert calls == []
    queued.pop()()
    assert calls == ['refresh', 'popup', 'refresh']
    assert app.icon.visible and not app._menu_presented
    app.stop_event.set()
    app._show_slice_menu()
    assert calls == ['refresh', 'popup', 'refresh']


@pytest.mark.parametrize('lang,words', [
    ('de', ('Genug Filament', 'Platte', 'danach', 'es fehlen', 'Zuordnung')),
    ('ru', ('Хватает', 'Пластина', 'после', 'не хватает', 'карта')),
    ('uk', ('Вистачає', 'Пластина', 'після', 'не вистачає', 'відповідність')),
    ('es', ('Suficiente', 'Placa', 'después', 'faltan', 'asignación')),
    ('en', ('Enough', 'Plate', 'after', 'short by', 'mapping')),
])
def test_forecast_menu_localizes_every_new_label(tmp_path, monkeypatch, lang, words):
    import sys
    class MenuItem:
        def __init__(self, text, action): self.text = text
    class Menu(tuple):
        SEPARATOR = None
        def __new__(cls, *items): return super().__new__(cls, items)
    monkeypatch.setitem(sys.modules, 'pystray', SimpleNamespace(MenuItem=MenuItem, Menu=Menu))
    store = Store(tmp_path, legacy_paths=())
    def seed(db):
        db['language'] = lang
        db['spools']['s'] = {'name':'TEST', 'material':'PLA', 'remaining_g':100}
        db['slots']['1'] = 's'
    store.update(seed)
    monkeypatch.setattr(spool_tracker, 'STORE', store)
    app = spool_tracker.TrayApp()
    app.forecast_service = ForecastService(store, lambda: None, tmp_path)
    app.forecast_service.state.accept([{'source':'project/Metadata/.1.0.gcode',
                                       'weights':[20,0,0,0], 'observed_at':1}])
    titles = ' '.join(i.text for i in app.build_menu() if i is not None)
    assert all(word in titles for word in (words[0], words[1], words[2], words[4]))
    store.update(lambda db: db['spools']['s'].update(remaining_g=1))
    assert words[3] in ' '.join(i.text for i in app.build_menu() if i is not None)
