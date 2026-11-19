import sys
from types import SimpleNamespace
import pytest
from macos_menu import configure_accessory_panel
from storage import printer_config, ValidationError


def test_accessory_uses_native_window_lifecycle_and_activates_on_reopen(monkeypatch):
    calls=[]
    class Window:
        def collectionBehavior(self):return 1
        def setCollectionBehavior_(self,v):calls.append(('space',v))
        def isMiniaturized(self):return getattr(self,'mini',False)
        def deminiaturize_(self,v):calls.append(('restore',v));self.mini=False
        def makeKeyAndOrderFront_(self,v):calls.append(('show',v))
    monkeypatch.setitem(sys.modules,'AppKit',SimpleNamespace(NSWindowCollectionBehaviorCanJoinAllSpaces=1,NSWindowCollectionBehaviorMoveToActiveSpace=2))
    monkeypatch.setitem(sys.modules,'PyObjCTools',SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda fn,*a:fn(*a))))
    first_show=object()
    view=SimpleNamespace(WindowHost=Window,first_show=first_show,app=SimpleNamespace(activateIgnoringOtherApps_=lambda value:calls.append(('activate',value))))
    cocoa=SimpleNamespace(BrowserView=view)
    configure_accessory_panel(cocoa)
    assert view.WindowHost is Window and view.first_show is first_show
    window=Window();instance=SimpleNamespace(window=window)
    view.show(instance)
    assert calls==[('space',2),('show',None),('activate',True)]
    window.mini=True;calls.clear();view.show(instance)
    assert calls==[('space',2),('restore',None),('show',None),('activate',True)]
    show=view.show;configure_accessory_panel(cocoa);assert view.show is show


@pytest.mark.parametrize('host',['192.1168.2.133','192.168.2.999','192.168.2','192.168..133'])
def test_invalid_numeric_address_is_not_sent_to_dns(host):
    with pytest.raises(ValidationError,match='IPv4'):
        printer_config({'host':host,'port':7125,'enabled':False})
