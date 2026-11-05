"""UI preview on fake inventory; no printer or external server is contacted."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import json
import tempfile
from http.server import ThreadingHTTPServer
import spool_tracker as app
from storage import Store
from spoolman_bridge import Bridge

root=Path(tempfile.mkdtemp(prefix='tracker-spoolman-ui-'))
store=Store(root/'inventory')
store.update(lambda db: db.update(language='ru'))
class Fake:
    def catalog(self):
        return {str(i): {'id':i,'name':name,'material':'PLA','remaining_g':amount,'archived':False,'color':color}
                for i,name,amount,color in [(1,'White PLA',616.317,'#ffffff'),(2,'Black PLA',231.67,'#222222'),(3,'Orange PLA',856.562,'#ff8000')]}
bridge=Bridge(store,lambda url:Fake())
bridge.configure('http://127.0.0.1:7912','read');bridge.attach(1,0)
class Handler(app.WebHandler):pass
Handler.store=store
Handler.spoolman_bridge=bridge
# Printer APIs are blocked; allow only Spoolman routes in this fake-only preview.
class Preview(Handler):
    def do_GET(self):
        if self.path.startswith('/api/printer/'):
            return self._response(403, {'error':'Offline preview'})
        return super().do_GET()
    def do_POST(self):
        if self.path.startswith(('/api/printer/','/api/guard/','/api/accounting/','/api/sender/')):
            return self._response(403, {'error':'Offline preview'})
        return super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',0),Preview)
app.WEB_PORT=server.server_port
Path('/tmp/tracker-spoolman-ui.json').write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}','root':str(root)}))
print(f'http://127.0.0.1:{server.server_port}',flush=True)
try:server.serve_forever()
finally:server.server_close()
