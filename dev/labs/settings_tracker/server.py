"""Real Tracker HTTP handlers with disposable storage and fixture-only Spoolman."""
import json
import socket
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
import spool_tracker
from storage import Store
from spoolman_bridge import Bridge, blank, catalog_item

URL = 'http://127.0.0.1:1'
class Fixture:
    def catalog(self):
        return {str(i): catalog_item({'id': i, 'remaining_weight': grams, 'archived': False,
            'filament': {'name': name, 'vendor': {'name': 'ELEGOO'}, 'material': mat, 'color_hex': color}})
            for i,name,mat,color,grams in [
                (1,'RAPID PETG White','PETG','efefed',1000),
                (2,'RAPID PETG Green','PETG','35b99d',995.26),
                (3,'Matte White','PLA','e6e4df',1000),
                (4,'ABS Gray','ABS','8390a0',1000),
                (5,'PLA Black','PLA','242830',780),
                (6,'TPU 95A Purple','TPU','b77ddf',640),
                (7,'Silk PLA Gold','PLA','d7b554',920)]}
    def request(self,*args,**kwargs):
        raise RuntimeError('External requests are disabled in the settings lab')

def deny_connection(*args, **kwargs):
    raise RuntimeError('Outgoing connections are disabled in the settings lab')

class Lab:
    def __init__(self, directory):
        self.store=Store(Path(directory)/'inventory', legacy_paths=())
        fixture=Fixture()
        def factory(url):
            if url != URL: raise ValueError('This lab accepts only its fixture URL: '+URL)
            return fixture
        self.bridge=Bridge(self.store,factory)
        def seed(db):
            db['language']='ru'
            db['spoolman']=blank()
            db['spools']['local']={'name':'НИТ PETG дымчатый','material':'PETG','remaining_g':1000,'color':'#607078'}
            db['slots']['4']='local'
        self.store.update(seed)
        self.bridge.configure(URL,'read')
        for sid,slot in [(2,0),(1,1),(3,2)]: self.bridge.attach(sid,slot)
        class Handler(spool_tracker.WebHandler):
            def do_GET(self):
                if self.path == '/favicon.ico': return self._response(200,b'','image/x-icon')
                if self.path not in ('/','/index.html','/api/data','/api/statistics','/api/forecast','/api/sender/status','/api/spoolman/status','/api/spoolman/compare'):
                    return self._response(403,{'error':'Стенд: подключение к принтеру и внешние действия отключены'})
                return super().do_GET()
            def do_POST(self):
                if self.path not in ('/api/lang','/api/settings','/api/printer/config','/api/slots','/api/spools/add','/api/spools/update','/api/spools/delete','/api/spools/color','/api/spoolman/configure','/api/spoolman/refresh','/api/spoolman/attach','/api/spoolman/detach','/api/spoolman/sync-label','/api/spoolman/refresh-labels'):
                    return self._response(403,{'error':'Стенд: подключение к принтеру и внешние действия отключены'})
                return super().do_POST()
        Handler.store=self.store
        Handler.spoolman_bridge=self.bridge
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        spool_tracker.WEB_PORT=self.server.server_port
        # No worker/monitor is started. All client socket creation is additionally denied.
        socket.create_connection=deny_connection
        self.url='http://127.0.0.1:%d'%self.server.server_port
        spool_tracker.HTML_PAGE=spool_tracker.HTML_PAGE.replace('<body>', '<body><div style="padding:10px;text-align:center;background:#24344f;color:#cde1ff">Тестовый Tracker · отдельная база · принтер и внешние соединения отключены</div>')
    def run(self): self.server.serve_forever()

def main():
    root=Path(__file__).resolve().parents[3]/'output'
    root.mkdir(exist_ok=True)
    directory=tempfile.mkdtemp(prefix='settings-tracker-',dir=root)
    lab=Lab(directory)
    print(json.dumps({'url':lab.url,'directory':directory}),flush=True)
    lab.run()
if __name__=='__main__': main()
