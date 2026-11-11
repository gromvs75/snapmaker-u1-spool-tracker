import json
from pathlib import Path
import tempfile
import threading
from http.server import ThreadingHTTPServer

import spool_tracker
from storage import Store
from spoolman_bridge import Bridge, blank, catalog_item, remote_id

URL = 'http://127.0.0.1:1'


class CatalogFixture:
    def catalog(self):
        return {str(i): catalog_item({'id': i, 'remaining_weight': weight, 'archived': False,
                'filament': {'name': name, 'vendor': {'name': 'ELEGOO'}, 'material': material, 'color_hex': color}})
                for i, name, material, color, weight in [
                    (2, 'RAPID PETG Green', 'PETG', '35b99d', 995.26),
                    (1, 'RAPID PETG White', 'PETG', 'efefed', 1000),
                    (3, 'Matte White', 'PLA', 'e6e4df', 1000)]}

    def request(self, *args, **kwargs):
        raise AssertionError('No remote writes or printer connections in this preview')


class Demo:
    def __init__(self, root):
        self.root = Path(root)
        self.store = Store(self.root / 'inventory', legacy_paths=())
        fixture = CatalogFixture()
        def factory(url):
            assert url == URL
            return fixture
        self.bridge = Bridge(self.store, factory)
        def seed(db):
            import time
            db['language'] = 'ru'
            db['spoolman'] = blank()
            db['spoolman'].update(url=URL, mode='read', epoch='offline-preview', checked_at=time.time(), catalog=fixture.catalog())
            for idx, item in enumerate(fixture.catalog().values()):
                sid = remote_id(URL, item['id'])
                db['spools'][sid] = {'name': '[Spoolman #%d] %s' % (item['id'], item['filament_name']),
                                    'material': item['material'], 'remaining_g': item['remaining_g'],
                                    'color': item['color'], 'spoolman': {'url': URL, 'id': item['id']}}
                db['slots'][str(idx + 1)] = sid
            db['spools']['local'] = {'name': 'НИТ PETG дымчатый', 'material': 'PETG', 'remaining_g': 1000, 'color': '#50565a'}
            db['slots']['4'] = 'local'
        self.store.update(seed)
        class Handler(spool_tracker.WebHandler):
            def do_GET(self):
                if self.path == '/favicon.ico':
                    return self._response(200, b'', 'image/x-icon')
                if self.path not in ('/', '/index.html', '/api/data', '/api/statistics', '/api/forecast',
                                     '/api/sender/status', '/api/spoolman/status', '/api/spoolman/compare'):
                    return self._response(403, {'error': 'Offline comparison preview only'})
                return super().do_GET()

            def do_POST(self):
                if self.path not in ('/api/spoolman/sync-label', '/api/spoolman/refresh-labels'):
                    return self._response(403, {'error': 'Offline comparison preview only'})
                return super().do_POST()
        Handler.store = self.store
        Handler.spoolman_bridge = self.bridge
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        port = self.server.server_port
        spool_tracker.WEB_PORT = port
        self.url = 'http://127.0.0.1:%d' % port

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)


def main():
    root = Path(__file__).resolve().parents[3] / 'output'
    root.mkdir(exist_ok=True)
    directory = tempfile.mkdtemp(prefix='compare-preview-', dir=root)
    with Demo(directory) as demo:
        print(json.dumps({'url': demo.url + '/#spoolman-compare', 'directory': directory}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
