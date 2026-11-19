"""Native shell for the isolated UID application; never exposes native objects to JS."""
import os
import sys
import threading
import time


class UidWindow:
    def __init__(self, url, storage_path, *, webview_module=None, title='Snapmaker U1 Spool Tracker 2.0 · стенд', tray_title='Tracker 2.0 · стенд', forecast=None):
        if webview_module is None:
            import webview as webview_module
        self._webview = webview_module
        # WKWebView otherwise navigates to blob: instead of showing Save As.
        if hasattr(webview_module, 'settings'):
            webview_module.settings['ALLOW_DOWNLOADS'] = True
            # Explicit opt-in for the disposable native GUI bench. Never enable
            # a debugging port for the normal installed profile.
            port = os.environ.get('TRACKER_BENCH_WEBVIEW_PORT')
            if port and os.environ.get('TRACKER20_DATA_DIR'):
                if not port.isascii() or not port.isdecimal() or not 1024 <= int(port) <= 65535:
                    raise ValueError('Invalid isolated WebView debugging port')
                webview_module.settings['REMOTE_DEBUGGING_PORT'] = int(port)
        self._storage_path = str(storage_path)
        self._tray_title = tray_title
        self._forecast = forecast
        self._started_at_ns = time.time_ns()
        self._tray_stop = threading.Event()
        self._menu_presented = False
        self._ready = False
        self._quitting = False
        self._pending_show = False
        width, height = 1202, 950
        position = {}
        if sys.platform == 'win32':
            import ctypes
            from ctypes.wintypes import RECT
            work = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
                width = min(width, work.right-work.left-32)
                height = min(height, work.bottom-work.top-32)
                position = dict(x=work.left+16, y=work.top+16)
        self._window = webview_module.create_window(
            title, url,
            width=width, height=height, min_size=(min(700,width), min(560,height)), **position)
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
        self._tray_stop.set()
        if self._ready:
            self._window.destroy()

    def hide(self):
        threading.Thread(target=self._window.hide,daemon=True).start()

    def show_forecast(self, *_):
        def open_view():
            self.show()
            if self._ready:
                self._window.evaluate_js('window.showLatestForecast && window.showLatestForecast()')
        threading.Thread(target=open_view,daemon=True).start()

    def _watch_forecast(self, tray):
        import logging
        from tracker_user_tray import tray_model, build_menu, create_tray_icon
        last=None;last_event=None;first=True
        def refresh(model, popup):
            if self._quitting or self._menu_presented:return
            tray.menu=build_menu(model,self.show,self.show_forecast,self.quit)
            tray.icon=create_tray_icon(model['status'])
            if popup and sys.platform=='darwin' and self._can_popup_forecast():
                self._menu_presented=True
                try:
                    logging.getLogger('tracker20').info('Opening tray for newly completed slice')
                    tray.visible=True
                    tray._status_item.button().performClick_(None)
                except Exception:logging.getLogger('tracker20').exception('Slice menu could not open')
                finally:self._menu_presented=False
        while not self._tray_stop.is_set():
            try:
                model=tray_model(self._forecast.snapshot())
                if model!=last:
                    # Rediscovery goes pending -> ready after startup as well.
                    # It is not a new slicing event and must not open a modal
                    # NSMenu during the window's first presentation.
                    popup=(not first and model['event'] is not None
                           and model['event']!=last_event
                           and model['event'][1] > self._started_at_ns)
                    if sys.platform=='darwin':
                        from PyObjCTools import AppHelper
                        AppHelper.callAfter(refresh,model,popup)
                    else:refresh(model,False)
                    if model['event'] is not None:last_event=model['event']
                    first=False;last=model
            except Exception:logging.getLogger('tracker20').exception('Tray forecast refresh failed')
            self._tray_stop.wait(1)

    def _can_popup_forecast(self):
        """Called on Cocoa's main thread immediately before opening NSMenu.

        The visible dashboard already displays the forecast. Modal menu tracking
        can interrupt its initial window animation/paint, so only auto-open the
        menu when the dashboard is hidden or minimized. Manual tray clicks are
        unaffected. Check here, not in the worker: visibility can change while
        the refresh is queued.
        """
        native = getattr(self._window, 'native', None)
        return bool(self._ready and not self._quitting and native is not None
                    and (not native.isVisible() or native.isMiniaturized()))

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
        tray = pystray.Icon('tracker-uid', icon, self._tray_title,
            menu=pystray.Menu(pystray.MenuItem('Открыть Tracker', self.show, default=True),
                              pystray.MenuItem('Выход', self.quit)))
        watcher=None
        if self._forecast is not None:
            from tracker_user_tray import tray_model,build_menu,create_tray_icon,install_macos_toolhead_icons
            model=tray_model(self._forecast.snapshot())
            tray.icon=create_tray_icon(model['status'])
            tray.menu=build_menu(model,self.show,self.show_forecast,self.quit)
            if sys.platform=='darwin':install_macos_toolhead_icons(tray)
        tray.run_detached()
        if self._forecast is not None:
            watcher=threading.Thread(target=self._watch_forecast,args=(tray,),name='tracker20-tray')
            watcher.start()
        try:
            if sys.platform == 'darwin':
                # Match 1.3.3: Cocoa imports set Regular, so override afterwards.
                from webview.platforms import cocoa
                from macos_menu import configure_accessory_panel
                from tracker_macos import configure_navigation
                import AppKit
                configure_navigation(cocoa)
                configure_accessory_panel(cocoa)
                AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                    AppKit.NSApplicationActivationPolicyAccessory)
            self._webview.start(gui='edgechromium' if sys.platform == 'win32' else None,
                                 private_mode=True, storage_path=self._storage_path)
        finally:
            self._tray_stop.set()
            if watcher:watcher.join()
            tray.stop()
