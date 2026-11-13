"""Loopback-only Spoolman read fixture; all write requests are rejected."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/v1/info':data={'version':'0.27.1'}
        elif self.path.startswith('/api/v1/spool?'):
            data=[{'id':42,'remaining_weight':123.456,'filament':{'name':'PLA Deep Blue','vendor':{'name':'Maker'},'material':'PLA','color_hex':'0088ff'}},
                  {'id':43,'remaining_weight':99.999,'filament':{'name':'Maker PETG','vendor':{'name':'Maker'},'material':'PETG','color_hex':'ff8800'}}]
        else:self.send_error(404);return
        raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
if __name__=='__main__':HTTPServer(('127.0.0.1',18899),Handler).serve_forever()
