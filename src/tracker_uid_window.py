"""Native shell for the isolated UID application; never exposes native objects to JS."""
import sys
import threading


class UidWindow:
    def __init__(self, url, storage_path, *, webview_module=None):
        if webview_module is None:
            import webview as webview_module
        self._webview = webview_module
        self._storage_path = str(storage_path)
        self._ready = False
        self._quitting = False
        self._pending_show = False
        self._window = webview_module.create_window(
            'Snapmaker U1 Spool Tracker 2.0 · стенд', url,
            width=1202, height=950, min_size=(700, 560))
        self._window.events.shown += self._shown
        self._window.events.closing += self._closing

    def _shown(self):
        self._ready = True
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
