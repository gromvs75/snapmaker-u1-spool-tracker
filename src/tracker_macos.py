"""Candidate-only Cocoa storage isolation and navigation diagnostics."""
import logging


def configure_navigation(cocoa):
    import objc
    view = cocoa.BrowserView
    if getattr(view, '_tracker_navigation_installed', False):
        return
    logger = logging.getLogger('tracker20')

    class TrackerNavigationDelegate(view.BrowserDelegate):
        def webView_didFinishNavigation_(self, webview, navigation):
            logger.info('Native navigation finished')
            objc.super(TrackerNavigationDelegate, self).webView_didFinishNavigation_(webview, navigation)
            # NSPanel can finish navigation before its backing surface has
            # committed the first layout. Do not reload the document or data.
            from PyObjCTools import AppHelper
            def layout():
                webview.setNeedsLayout_(True)
                webview.layoutSubtreeIfNeeded()
                webview.setNeedsDisplay_(True)
                if webview.window():webview.window().displayIfNeeded()
            AppHelper.callAfter(layout)
            def inspected(value, error):
                window = webview.window()
                logger.info('Native DOM probe result=%s error=%s frame=%s attached=%s window_id=%s visible=%s minimized=%s occlusion=%s',
                            value, error, webview.frame(), bool(window),
                            window.windowNumber() if window else None,
                            bool(window.isVisible()) if window else None,
                            bool(window.isMiniaturized()) if window else None,
                            int(window.occlusionState()) if window else None)
            webview.evaluateJavaScript_completionHandler_(
                'JSON.stringify({ready:document.readyState,body:document.body?.innerText.length,nav:!!document.getElementById("nav-overview"),width:innerWidth,height:innerHeight,visibility:document.visibilityState,background:document.body?getComputedStyle(document.body).backgroundColor:null})', inspected)

        def webView_didFailProvisionalNavigation_withError_(self, webview, navigation, error):
            logger.error('Native navigation failed domain=%s code=%s description=%s',
                         error.domain(), error.code(), error.localizedDescription())

        def webView_didFailNavigation_withError_(self, webview, navigation, error):
            self.webView_didFailProvisionalNavigation_withError_(webview, navigation, error)

        def webViewWebContentProcessDidTerminate_(self, webview):
            logger.error('Native WebKit content process terminated')

    # WKWebView copies its configuration during initialization. pywebview's
    # Cocoa backend sets its datastore too late and asynchronously clears the
    # default store during the first navigation. Never use or clear that shared
    # store: this candidate's durable data belongs to SQLite, not WebKit.
    webkit = cocoa.WebKit
    class PrivateConfiguration:
        @classmethod
        def alloc(cls):
            return cls()
        def init(self):
            configuration = webkit.WKWebViewConfiguration.alloc().init()
            configuration.setWebsiteDataStore_(webkit.WKWebsiteDataStore.nonPersistentDataStore())
            return configuration
    class PrivateWebKit:
        WKWebViewConfiguration = PrivateConfiguration
        def __getattr__(self, name):
            return getattr(webkit, name)
    cocoa.WebKit = PrivateWebKit()

    original_init = view.__init__
    def initialize(instance, *args, **kwargs):
        private = cocoa._state['private_mode']
        cocoa._state['private_mode'] = False  # skip backend's clear-default-store operation
        try:
            original_init(instance, *args, **kwargs)
            instance.datastore = instance.webview.configuration().websiteDataStore()
            logger.info('Native WebKit private store=%s', not instance.datastore.isPersistent())
        finally:
            cocoa._state['private_mode'] = private

    view.__init__ = initialize
    view.BrowserDelegate = TrackerNavigationDelegate
    view._tracker_navigation_installed = True
