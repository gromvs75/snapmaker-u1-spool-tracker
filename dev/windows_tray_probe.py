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
faulthandler.dump_traceback_later(15, repeat=True)
print("PROBE imports", flush=True)

import spool_tracker
from pystray._util import win32

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemCount.restype = ctypes.c_int
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
        app.window_controller.show()
        record(result='PASS')
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
    app.run()
    assert any(row.get('result') == 'PASS' for row in results), results
