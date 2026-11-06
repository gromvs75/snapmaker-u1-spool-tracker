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
        def raise_panel():
            window = instance.window
            behavior = window.collectionBehavior()
            window.setCollectionBehavior_((behavior & ~AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)
                                          | AppKit.NSWindowCollectionBehaviorMoveToActiveSpace)
            if window.isMiniaturized():
                window.deminiaturize_(None)
            window.makeKeyAndOrderFront_(None)
            # A nonactivating app cannot otherwise reliably pass another app's key window.
            window.orderFrontRegardless()
        AppHelper.callAfter(raise_panel)

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
