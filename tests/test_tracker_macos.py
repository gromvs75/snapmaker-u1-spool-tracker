import sys
from types import SimpleNamespace
import pytest
from tracker_macos import configure_navigation


def test_private_store_precedes_webview_creation_and_never_clears_default(monkeypatch):
    calls=[]
    class Config:
        @classmethod
        def alloc(cls):return cls()
        def init(self):return self
        def setWebsiteDataStore_(self,store):self.store=store;calls.append('store configured')
        def websiteDataStore(self):return self.store
    store=SimpleNamespace(isPersistent=lambda:False)
    webkit=SimpleNamespace(WKWebViewConfiguration=Config,WKWebsiteDataStore=SimpleNamespace(nonPersistentDataStore=lambda:store))
    class View:
        BrowserDelegate=object
        def __init__(self,fail=False):
            assert cocoa._state['private_mode'] is False
            config=cocoa.WebKit.WKWebViewConfiguration.alloc().init()
            assert config.store is store
            calls.append('webview created')
            if fail:raise RuntimeError('construction failed')
            self.webview=SimpleNamespace(configuration=lambda:config)
    cocoa=SimpleNamespace(BrowserView=View,WebKit=webkit,_state={'private_mode':True})
    monkeypatch.setitem(sys.modules,'objc',SimpleNamespace())
    configure_navigation(cocoa)
    assert View().datastore is store
    assert calls==['store configured','webview created']
    assert cocoa._state['private_mode'] is True
    assert cocoa.WebKit.WKWebsiteDataStore is webkit.WKWebsiteDataStore
    with pytest.raises(RuntimeError):View(fail=True)
    assert cocoa._state['private_mode'] is True
    init=View.__init__;configure_navigation(cocoa);assert View.__init__ is init
