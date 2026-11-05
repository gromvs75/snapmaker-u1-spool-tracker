"""Keep a windowed accessory application's menu bar visible after activation."""

def install_menu_bar_recovery():
    import AppKit
    from PyObjCTools import AppHelper
    app = AppKit.NSApplication.sharedApplication()

    def recover(_notification=None):
        # Notifications can arrive before the Space transition has completed.
        AppHelper.callAfter(restore)

    def restore():
        window = app.keyWindow()
        if not app.isActive() or window is None or not window.isVisible():
            return
        if window.styleMask() & AppKit.NSWindowStyleMaskFullScreen:
            return
        # Do not change Dock policy, global preferences or full-screen behaviour.
        if not AppKit.NSMenu.menuBarVisible():
            AppKit.NSMenu.setMenuBarVisible_(True)

    center = AppKit.NSNotificationCenter.defaultCenter()
    workspace = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
    tokens = []
    for owner, event in [
        (center, AppKit.NSApplicationDidBecomeActiveNotification),
        (center, AppKit.NSWindowDidBecomeKeyNotification),
        (workspace, AppKit.NSWorkspaceActiveSpaceDidChangeNotification),
    ]:
        tokens.append((owner, owner.addObserverForName_object_queue_usingBlock_(event, None, None, recover)))
    return tokens  # Retain observers for the GUI loop's lifetime.
