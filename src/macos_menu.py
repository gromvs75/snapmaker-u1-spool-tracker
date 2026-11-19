"""Accessory application using the normal Cocoa window lifecycle.

WKWebView must receive activation and visibility events. A nonactivating NSPanel
can leave its document hidden and its native surface blank on recent macOS.
Accessory activation policy is set by the shell and keeps Tracker out of Dock.
"""


def configure_accessory_panel(cocoa):
    import AppKit
    from PyObjCTools import AppHelper
    view = cocoa.BrowserView
    if getattr(view, '_tracker_panel_installed', False):
        return

    def show(instance):
        def raise_window():
            window = instance.window
            behavior = window.collectionBehavior()
            window.setCollectionBehavior_((behavior & ~AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)
                                          | AppKit.NSWindowCollectionBehaviorMoveToActiveSpace)
            if window.isMiniaturized():
                window.deminiaturize_(None)
            window.makeKeyAndOrderFront_(None)
            view.app.activateIgnoringOtherApps_(True)
        AppHelper.callAfter(raise_window)

    # Retain the backend's NSWindow, first_show and deferred WKWebView attachment.
    view.show = show
    view._tracker_panel_installed = True
