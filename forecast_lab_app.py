"""Separate inventory-backed Overview lab. No printer monitor, sender, or user Store."""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from slice_observer import SliceObserver

STOCK = (100, 50, 25, 110)


def load_lab_stock(source):
    config = source / 'forecast-stock.json'
    if not config.exists():
        return STOCK
    values = json.loads(config.read_text())['stock_g']
    if (not isinstance(values, list) or len(values) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values)):
        raise ValueError('Lab stock must contain four finite nonnegative weights')
    return tuple(values)


from forecast import ForecastState, forecast_entry



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixtures', action='store_true', help='Watch a fresh synthetic lab directory')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='tracker-overview-lab-'))
    stock = STOCK
    if args.fixtures:
        watch = root / 'slices'
        watch.mkdir()
    else:
        source = Path('/tmp/tracker-gui-slice-lab').resolve(strict=True)
        if (source / 'GUI_SLICE_LAB_ONLY').read_text() != 'offline-gui-only\n':
            raise RuntimeError('Isolated Snorca marker required')
        stock = load_lab_stock(source)
        watch = source / 'tmp/snapmaker_orca_model'
    from storage import Store
    import spool_tracker
    spool_tracker.APP_VERSION = "1.2-alpha · Forecast Lab"
    from forecast_view import install
    import webview
    inventory_root = root / 'inventory' if args.fixtures else source / 'forecast-inventory-v5'
    store = Store(inventory_root, legacy_paths=())
    def seed(db):
        db['language'] = 'ru'
        db['safety_margin_g'] = 5
        db['printer']['enabled'] = False
        db['spools'] = {f's{i}': {'name': f'Тестовая PLA {i+1}', 'material': 'PLA',
                        'remaining_g': stock[i], 'color': ['#202727','#eeeeee','#ff821e','#ef3025'][i]}
                        for i in range(4)}
        db['slots'] = {str(i+1): f's{i}' for i in range(4)}
    if not store.path.exists():
        store.update(seed)
    original = store.path.read_bytes()
    state = ForecastState(stock, store=store)
    html = install(spool_tracker.BASE_HTML_PAGE).replace("1.1.0-beta.1", "1.2-alpha · Forecast Lab")
    html = html.replace('<span id="build-label" class="subtitle">1.1.0-beta.1</span>',
                        '<span id="build-label" class="subtitle">Forecast Lab · отдельная тестовая сборка</span>')
    class Handler(spool_tracker.WebHandler):
        def _allowed_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
        def do_GET(self):
            if not self._allowed_host():
                return self._response(403, {'error': 'Invalid host'})
            if self.path in ('/', '/index.html'):
                return self._response(200, html.encode(), 'text/html; charset=utf-8')
            if self.path == '/api/forecast':
                return self._response(200, state.snapshot())
            if self.path not in ('/api/data', '/api/statistics', '/api/sender/status'):
                return self._response(403, {'error': 'Read-only isolated lab'})
            return super().do_GET()
        def do_POST(self):
            # Only explicit inventory operations on this temporary Store. No printer/sender/accounting.
            if self.path not in ('/api/spools/update', '/api/spools/add', '/api/spools/delete',
                                 '/api/spools/color', '/api/slots', '/api/settings'):
                return self._response(403, {'error': 'Only isolated inventory edits are allowed'})
            return super().do_POST()
    Handler.store = store
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    spool_tracker.WEB_PORT = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()
    loaded = threading.Event()
    from forecast_backup import ForecastBackupBridge
    bridge = ForecastBackupBridge(store, webview, root)
    url = f'http://127.0.0.1:{server.server_port}'
    window = webview.create_window('Tracker Forecast Lab · Обзор · ТЕСТОВЫЕ ДАННЫЕ', url,
                                  js_api=bridge, width=1160, height=920, min_size=(800, 600))
    bridge.window = window
    window.events.loaded += loaded.set
    counts = {'auto_shows': 0}
    def reveal():
        window.show()
        window.restore()
        window.evaluate_js('refreshSliceForecast(); setView("overview");')
        from AppKit import NSApplication
        from PyObjCTools import AppHelper
        AppHelper.callAfter(NSApplication.sharedApplication().activateIgnoringOtherApps_, True)
    def worker():
        observer = SliceObserver(watch)
        loaded.wait()
        while not stop.is_set():
            try:
                events = observer.poll()
                state.accept(events)
                if events:
                    reveal()
                    counts['auto_shows'] += 1
            except Exception as exc:
                with state.lock:
                    state.error = str(exc)
            report = dict(state.snapshot(), **counts, root=str(root), watch=str(watch), url=url,
                          inventory_unchanged=store.path.read_bytes() == original)
            temp = root / 'report.tmp'
            temp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            temp.replace(root / 'report.json')
            stop.wait(.3)
    def start():
        from AppKit import NSObject, NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSApplication
        from PyObjCTools import AppHelper
        class Tray(NSObject):
            def show_(self, sender):
                window.show()
                window.restore()
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            def quit_(self, sender):
                window.destroy()
        def tray():
            controller = Tray.alloc().init()
            item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            item.button().setTitle_('U1 Прогноз · тест')
            menu = NSMenu.alloc().init()
            for title, action in [('Открыть Обзор', 'show:'), ('Завершить тестовый Tracker', 'quit:')]:
                choice = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
                choice.setTarget_(controller)
                menu.addItem_(choice)
            item.setMenu_(menu)
            bridge.tray = (controller, item, menu)
        AppHelper.callAfter(tray)
        worker()
    print(json.dumps({'root':str(root), 'url':url, 'watch':str(watch)}), flush=True)
    try:
        webview.start(start, private_mode=True, storage_path=str(root / 'webview'))
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
