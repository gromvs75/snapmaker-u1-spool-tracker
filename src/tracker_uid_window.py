"""Native shell for the isolated UID application; never exposes native objects to JS."""
import sys
import threading


class UidWindow:
    def __init__(self, url, storage_path, *, webview_module=None):
        if webview_module is None:
            import webview as webview_module
        self._webview = webview_module
        # WKWebView otherwise navigates to blob: instead of showing Save As.
        if hasattr(webview_module, 'settings'):
            webview_module.settings['ALLOW_DOWNLOADS'] = True
        self._storage_path = str(storage_path)
        self._ready = False
        self._quitting = False
        self._pending_show = False
        width, height = 1202, 950
        if sys.platform == 'win32':
            import ctypes
            from ctypes.wintypes import RECT
            work = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
                width = min(width, work.right-work.left-32)
                height = min(height, work.bottom-work.top-32)
        self._window = webview_module.create_window(
            'Snapmaker U1 Spool Tracker 2.0 · стенд', url,
            width=width, height=height, min_size=(min(700,width), min(560,height)))
        self._window.events.shown += self._shown
        self._window.events.closing += self._closing

    def _shown(self):
        self._ready = True
        if sys.platform == 'darwin':
            self._route_macos_quit()
        if self._quitting:
            self._window.destroy()
        elif self._pending_show:
            self.show()

    def _closing(self):
        if self._quitting:
            return True
        # Calling hide synchronously inside WinForms Closing deadlocks dispatch.
        threading.Thread(target=self._window.hide, daemon=True).start()
        return False

    def show(self, *_):
        if self._quitting:
            return
        if not self._ready:
            self._pending_show = True
            return
        self._pending_show = False
        self._window.show()
        if sys.platform != 'darwin':
            self._window.restore()

    def quit(self, *_):
        self._quitting = True
        if self._ready:
            self._window.destroy()

    def _route_macos_quit(self):
        if hasattr(self, '_quit_target'):
            return
        # AppKit's default Quit asks every window to close, which our close-to-tray
        # policy cancels. Route Cmd+Q through explicit quit, like the tray action.
        try:
            import AppKit
            import objc
            from PyObjCTools import AppHelper
        except ImportError:
            return
        shell = self
        class TrackerQuitTarget(AppKit.NSObject):
            @objc.IBAction
            def quitTracker_(self, sender):
                threading.Thread(target=shell.quit, daemon=True).start()
        self._quit_target = TrackerQuitTarget.alloc().init()
        def install():
            menu = AppKit.NSApp.mainMenu().itemAtIndex_(0).submenu()
            for item in menu.itemArray():
                if str(item.action()) == 'terminate:':
                    item.setTarget_(self._quit_target)
                    item.setAction_('quitTracker:')
        AppHelper.callAfter(install)

    def run(self):
        import pystray
        from PIL import Image, ImageDraw
        icon = Image.new('RGBA', (64, 64), '#163c33')
        draw = ImageDraw.Draw(icon)
        draw.ellipse((8, 8, 56, 56), outline='white', width=5)
        draw.ellipse((25, 25, 39, 39), fill='white')
        tray = pystray.Icon('tracker-uid-bench', icon, 'Tracker 2.0 · стенд',
            menu=pystray.Menu(pystray.MenuItem('Открыть Tracker', self.show, default=True),
                              pystray.MenuItem('Выход', self.quit)))
        tray.run_detached()
        try:
            self._webview.start(gui='edgechromium' if sys.platform == 'win32' else None,
                                 private_mode=True, storage_path=self._storage_path)
        finally:
            tray.stop()
