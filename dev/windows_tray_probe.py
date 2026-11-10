"""Exercise the real Windows tray message loop using only a temporary inventory."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from ctypes import wintypes

import faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(30, repeat=True)
print("PROBE imports", flush=True)

import spool_tracker
from pystray._util import win32

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemCount.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
results = []


def record(**data):
    results.append(data)
    print(json.dumps(data), flush=True)


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Timed out waiting for ' + str(predicate))


def probe(app):
    try:
        wait_for(lambda: app.icon is not None and app.icon.visible)
        wait_for(lambda: app.window_controller.ready)
        assert app.window_controller.window.events.loaded.wait(15), "JS API did not load"
        record(api=app.window_controller.window.evaluate_js("Object.keys(window.pywebview.api).sort()"))
        icon = app.icon
        for attempt in range(3):
            time.sleep(2)
            menu = icon._menu_handle[0]
            count = user32.GetMenuItemCount(menu)
            record(attempt=attempt, menu_items=count, hwnd=icon._hwnd)
            assert count > 0, 'Native tray menu is invalid or empty'
            win32.PostMessage(icon._hwnd, win32.WM_NOTIFY, 0, win32.WM_RBUTTONUP)
            try:
                popup = wait_for(lambda: user32.FindWindowW('#32768', None), timeout=3)
                record(popup=popup)
            finally:
                win32.PostMessage(icon._menu_hwnd, 0x001F, 0, 0)  # WM_CANCELMODE
            app._schedule_menu_refresh()
        app._open_dashboard()
        native = app.window_controller.window.native.Handle.ToInt64()
        wait_for(lambda: user32.IsWindowVisible(native))
        app.window_controller.window.evaluate_js("window.pywebview.api.hide(); true")
        wait_for(lambda: not user32.IsWindowVisible(native))
        app._open_dashboard()
        wait_for(lambda: user32.IsWindowVisible(native))
        record(result='PASS', window='shown, hidden through JS API, reopened')
    except Exception as exc:
        record(result='FAIL', error=repr(exc))
    finally:
        app._quit()


with tempfile.TemporaryDirectory(prefix='tracker-tray-probe-') as directory:
    root = Path(directory)
    (root / 'ISOLATED_TRACKER_TEST').write_text('offline-only\n')
    spool_tracker.configure_runtime(['--isolated-root', str(root)])
    spool_tracker.configure_logging()
    # Capture errors from the tray library, which release rc1 did not log.
    import logging
    logging.getLogger('pystray').addHandler(logging.StreamHandler())
    app = spool_tracker.TrayApp()
    def watchdog():
        time.sleep(40)
        record(result='FAIL', error='GUI did not exit before watchdog')
        os._exit(2)
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=probe, args=(app,), daemon=True).start()
    print("PROBE app.run", flush=True)
    try:
        assert app.run() == 0
    finally:
        faulthandler.cancel_dump_traceback_later()
        logging.shutdown()
    assert any(row.get('result') == 'PASS' for row in results), results
