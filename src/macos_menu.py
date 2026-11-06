"""Nonactivating Cocoa dashboard for a menu-bar-only application.

Keep the previous application's system menu bar while allowing input in Tracker.
The nonactivating style must be set at NSPanel creation, not toggled afterward.
"""

def configure_accessory_panel(cocoa):
    import AppKit
    import objc
    from PyObjCTools import AppHelper
    view = cocoa.BrowserView
    if getattr(view, '_tracker_panel_installed', False):
        return

    class TrackerDashboardPanel(AppKit.NSPanel):
        def initWithContentRect_styleMask_backing_defer_(self, rect, style, backing, defer):
            self = objc.super(TrackerDashboardPanel, self).initWithContentRect_styleMask_backing_defer_(
                rect, style | AppKit.NSWindowStyleMaskNonactivatingPanel, backing, defer)
            if self is not None:
                self.setFloatingPanel_(False)
                self.setHidesOnDeactivate_(False)
                self.setBecomesKeyOnlyIfNeeded_(False)
                self.setLevel_(AppKit.NSNormalWindowLevel)
                self.setAccessibilityRole_(AppKit.NSAccessibilityWindowRole)
            return self

        def canBecomeKeyWindow(self):
            return getattr(self, 'focus', True)

        def canBecomeMainWindow(self):
            return False

    def show(instance):
        # Unlike pywebview's default show(), do not activate an accessory app.
        AppHelper.callAfter(instance.window.makeKeyAndOrderFront_, None)

    def first_show(instance):
        instance.window.setContentView_(instance.webview)
        instance.window.makeFirstResponder_(instance.webview)
        if not instance.hidden:
            instance.window.makeKeyAndOrderFront_(None)
        if instance.maximized:
            instance.maximize()
        elif instance.minimized:
            instance.minimize()
        instance.shown.set()
        if not view.app.isRunning():
            AppHelper.installMachInterrupt()
            view.app.run()

    view.WindowHost = TrackerDashboardPanel
    view.show = show
    view.first_show = first_show
    view._tracker_panel_installed = True
