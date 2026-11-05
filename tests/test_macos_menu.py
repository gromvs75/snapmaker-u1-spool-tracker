import sys
from types import SimpleNamespace
from macos_menu import install_menu_bar_recovery


def test_recovery_is_scoped_to_active_nonfullscreen_window(monkeypatch):
    callbacks=[];scheduled=[];changes=[]
    center=SimpleNamespace(addObserverForName_object_queue_usingBlock_=lambda event,obj,queue,fn:callbacks.append(fn) or fn)
    window=SimpleNamespace(isVisible=lambda:True,styleMask=lambda:0)
    app=SimpleNamespace(isActive=lambda:True,keyWindow=lambda:window)
    menu=SimpleNamespace(menuBarVisible=lambda:False,setMenuBarVisible_=changes.append)
    fake=SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda:app),
        NSNotificationCenter=SimpleNamespace(defaultCenter=lambda:center),
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda:SimpleNamespace(notificationCenter=lambda:center)),
        NSMenu=menu,NSWindowStyleMaskFullScreen=16,NSApplicationDidBecomeActiveNotification='active',
        NSWindowDidBecomeKeyNotification='key',NSWorkspaceActiveSpaceDidChangeNotification='space')
    monkeypatch.setitem(sys.modules,'AppKit',fake)
    monkeypatch.setitem(sys.modules,'PyObjCTools',SimpleNamespace(AppHelper=SimpleNamespace(callAfter=scheduled.append)))
    assert len(install_menu_bar_recovery())==3
    callbacks[-1](None);assert changes==[]
    scheduled.pop()();assert changes==[True]
    changes.clear();app.isActive=lambda:False
    callbacks[0](None);scheduled.pop()();assert changes==[]
    app.isActive=lambda:True;window.styleMask=lambda:16
    callbacks[1](None);scheduled.pop()();assert changes==[]
    window.styleMask=lambda:0;menu.menuBarVisible=lambda:True
    callbacks[0](None);scheduled.pop()();assert changes==[]
