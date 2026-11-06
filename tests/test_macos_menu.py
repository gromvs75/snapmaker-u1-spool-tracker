import sys
from types import SimpleNamespace
import pytest
from macos_menu import configure_accessory_panel
from storage import printer_config, ValidationError


def test_panel_never_activates_application_and_sets_style_at_creation(monkeypatch):
    calls=[]
    class Panel:
        def initWithContentRect_styleMask_backing_defer_(self,r,s,b,d):
            self.style=s;return self
        def setFloatingPanel_(self,v):calls.append(('floating',v))
        def setHidesOnDeactivate_(self,v):calls.append(('hides',v))
        def setBecomesKeyOnlyIfNeeded_(self,v):pass
        def setLevel_(self,v):calls.append(('level',v))
        def setAccessibilityRole_(self,v):pass
        def setContentView_(self,v):pass
        def makeFirstResponder_(self,v):pass
        def makeKeyAndOrderFront_(self,v):calls.append(('show',v))
    monkeypatch.setitem(sys.modules,'AppKit',SimpleNamespace(NSPanel=Panel,NSWindowStyleMaskNonactivatingPanel=128,NSNormalWindowLevel=0,NSAccessibilityWindowRole='AXWindow'))
    monkeypatch.setitem(sys.modules,'objc',SimpleNamespace(super=super))
    monkeypatch.setitem(sys.modules,'PyObjCTools',SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda fn,*a:fn(*a),installMachInterrupt=lambda:None)))
    view=SimpleNamespace(app=SimpleNamespace(isRunning=lambda:False,run=lambda:calls.append(('run',True))))
    cocoa=SimpleNamespace(BrowserView=view)
    configure_accessory_panel(cocoa)
    panel=view.WindowHost().initWithContentRect_styleMask_backing_defer_(None,7,0,False)
    assert panel.style==135 and panel.canBecomeKeyWindow() and not panel.canBecomeMainWindow()
    assert ('floating',False) in calls and ('hides',False) in calls
    instance=SimpleNamespace(window=panel,webview=object(),hidden=True,maximized=False,minimized=False,shown=SimpleNamespace(set=lambda:None))
    view.first_show(instance)
    assert ('show',None) not in calls
    view.show(instance)
    assert calls[-1]==('show',None)
    configure_accessory_panel(cocoa) # no duplicate Objective-C class


@pytest.mark.parametrize('host',['192.1168.2.133','192.168.2.999','192.168.2','192.168..133'])
def test_invalid_numeric_address_is_not_sent_to_dns(host):
    with pytest.raises(ValidationError,match='IPv4'):
        printer_config({'host':host,'port':7125,'enabled':False})
