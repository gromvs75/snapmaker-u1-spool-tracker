"""Small macOS accessibility adapter for Snapmaker Orca's preprint WebView."""

from contextlib import contextmanager
import ctypes as c
import time

from tracker_orca_preprint import clean, preprint_address

BUNDLE_ID = 'com.snapmaker.snapmaker-orca'
# UI order and labels have been checked against this version of the bundled WebView.
SUPPORTED_VERSION = '2.4.1'
UTF8 = 0x08000100
PTR = c.c_void_p


def api(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


class Accessibility:
    def __init__(self):
        def framework(name):
            return c.CDLL(f'/System/Library/Frameworks/{name}.framework/{name}')

        ax = framework('ApplicationServices')
        cf = framework('CoreFoundation')
        self.trusted = api(ax, 'AXIsProcessTrusted', c.c_bool)
        self.application = api(ax, 'AXUIElementCreateApplication', PTR, c.c_int)
        self.timeout = api(ax, 'AXUIElementSetMessagingTimeout', c.c_int, PTR, c.c_float)
        self.copy_attribute = api(ax, 'AXUIElementCopyAttributeValue', c.c_int, PTR, PTR, c.POINTER(PTR))
        self.action = api(ax, 'AXUIElementPerformAction', c.c_int, PTR, PTR)
        self.release = api(cf, 'CFRelease', None, PTR)
        self.type = api(cf, 'CFGetTypeID', c.c_ulong, PTR)
        self.string_type = api(cf, 'CFStringGetTypeID', c.c_ulong)()
        self.url_type = api(cf, 'CFURLGetTypeID', c.c_ulong)()
        self.array_type = api(cf, 'CFArrayGetTypeID', c.c_ulong)()
        self.create_string = api(cf, 'CFStringCreateWithCString', PTR, PTR, c.c_char_p, c.c_uint32)
        self.copy_string = api(cf, 'CFStringGetCString', c.c_bool, PTR, c.c_char_p, c.c_long, c.c_uint32)
        self.url_string = api(cf, 'CFURLGetString', PTR, PTR)
        self.count = api(cf, 'CFArrayGetCount', c.c_long, PTR)
        self.at = api(cf, 'CFArrayGetValueAtIndex', PTR, PTR, c.c_long)

    @contextmanager
    def value(self, element, name):
        key = self.create_string(None, name.encode(), UTF8)
        result = PTR()
        try:
            status = self.copy_attribute(element, key, c.byref(result))
            yield result.value if status == 0 else None
        finally:
            if result.value:
                self.release(result)
            self.release(key)

    def text(self, element, name):
        with self.value(element, name) as value:
            if not value:
                return ''
            if self.type(value) == self.url_type:
                value = self.url_string(value)
            if value and self.type(value) == self.string_type:
                buffer = c.create_string_buffer(4096)
                if self.copy_string(value, buffer, len(buffer), UTF8):
                    return clean(buffer.value.decode('utf-8'))
        return ''

    @contextmanager
    def children(self, element, name='AXChildren'):
        with self.value(element, name) as value:
            if value and self.type(value) == self.array_type:
                yield [self.at(value, i) for i in range(min(self.count(value), 128))]
            else:
                yield []

    def press(self, element):
        action = self.create_string(None, b'AXPress', UTF8)
        try:
            self.action(element, action)
        finally:
            self.release(action)


class MacOrcaDialog:
    def __init__(self, accessibility=None):
        self.ax = accessibility if accessibility is not None else Accessibility()
        self.enabled = None

    def __call__(self):
        from AppKit import NSRunningApplication
        from Foundation import NSBundle
        import objc

        if not self.ax.trusted():
            return None
        with objc.autorelease_pool():
            applications = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
            if len(applications) != 1:
                return None
            app = applications[0]
            bundle = NSBundle.bundleWithURL_(app.bundleURL())
            if not bundle or str(bundle.objectForInfoDictionaryKey_('CFBundleShortVersionString')) != SUPPORTED_VERSION:
                return None
            return self.read_windows(app.processIdentifier())

    def read_windows(self, pid):
        app = self.ax.application(pid)
        if not app:
            return None
        try:
            self.ax.timeout(app, 0.12)
            results = []
            limit = time.monotonic() + 0.75
            with self.ax.children(app, 'AXWindows') as windows:
                for window in windows:
                    # Orca places the WKWebView in its own modal dialog.
                    if (self.ax.text(window, 'AXSubrole') not in ('AXDialog', 'AXSystemDialog')
                            and self.ax.text(window, 'AXTitle') not in ('Print Preprocessing', 'Print preset')):
                        continue
                    results.extend(self.find_documents(window, pid, limit))
            return results[0] if len(results) == 1 else None
        finally:
            self.ax.release(app)

    def find_documents(self, element, pid, limit, depth=0):
        if depth > 8 or time.monotonic() > limit:
            return []
        if self.ax.text(element, 'AXRole') == 'AXWebArea':
            url = self.ax.text(element, 'AXURL')
            address = preprint_address(url)
            if address is None:
                return []
            nodes = []
            self.read_controls(element, (pid, address), nodes, limit)
            return [(url, nodes)]
        with self.ax.children(element) as children:
            return [document for child in children
                    for document in self.find_documents(child, pid, limit, depth + 1)]

    def read_controls(self, element, identity, nodes, limit, depth=0):
        if depth > 14 or len(nodes) >= 80 or time.monotonic() > limit:
            return
        role = self.ax.text(element, 'AXRole')
        if role in ('AXButton', 'AXPopUpButton', 'AXStaticText', 'AXHeading'):
            labels = tuple(dict.fromkeys(filter(None, (self.ax.text(element, name)
                           for name in ('AXTitle', 'AXDescription', 'AXValue')))))
            if role == 'AXButton' and labels == ('Enable accessibility',):
                # Flutter keeps semantics disabled until its own accessibility
                # button is pressed. Only this verified control can be activated.
                if self.enabled != identity:
                    self.ax.press(element)
                    self.enabled = identity
            elif labels:
                nodes.append((role, labels))
            return
        with self.ax.children(element) as children:
            for child in children:
                self.read_controls(child, identity, nodes, limit, depth + 1)
