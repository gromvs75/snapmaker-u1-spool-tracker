"""Loopback HTTP/WebSocket protocol fixture, never controls hardware.

python -m dev.mock_sender_u1 --http-port 0 --ws-port 0
Prints endpoints; Ctrl-C stops. All files/jobs are kept only in memory.
"""
import argparse
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import urlsplit

from websockets.sync.server import serve


class MockSenderU1:
    def __init__(self, fault='', http_port=0, ws_port=0):
        self.fault = fault
        self.response_delay = .5
        self.files = {}
        self.uploads = []
        self.start_requests = []
        self.accepted_starts = []
        self.start_event = threading.Event()
        self.reads = []
        self.state = 'standby'
        self.filename = ''
        self.mapping = [0, 1, 2, 3]
        self.after_upload = None
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, result, code=200, raw=False):
                body = result if raw else json.dumps({'result': result}).encode()
                try:
                    self.send_response(code)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                stand.reads.append(self.path)
                if self.path.startswith('/printer/objects/query'):
                    self.respond({'status': {'webhooks': {'state': 'ready'},
                        'print_stats': {'state': 'printing' if stand.fault == 'busy' else stand.state,
                                        'filename': stand.filename},
                        'print_task_config': {'auto_replenish_filament': stand.fault == 'auto_replenish',
                                             'extruder_map_table': stand.mapping}}})
                elif self.path.startswith('/server/files/metadata?'):
                    from urllib.parse import parse_qs
                    name = parse_qs(urlsplit(self.path).query)['filename'][0]
                    self.respond({'size': len(stand.files.get(name, b''))})
                elif self.path.startswith('/server/files/gcodes/'):
                    name = self.path.rsplit('/', 1)[1]
                    data = stand.files.get(name, b'')
                    self.respond(data + (b'corrupt' if stand.fault == 'corrupt' else b''), raw=True)
                else:
                    self.respond({}, 404)

            def do_POST(self):
                if self.path != '/server/files/upload':
                    self.respond({}, 404)
                    return
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if stand.fault == 'upload_reject':
                    self.respond({}, 403)
                    return
                if stand.fault == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', 'http://192.0.2.1/forbidden')
                    self.end_headers()
                    return
                message = BytesParser(policy=default).parsebytes(
                    b'Content-Type: ' + self.headers['Content-Type'].encode() + b'\r\nMIME-Version: 1.0\r\n\r\n' + raw)
                fields = {}
                filename = None
                for part in message.iter_parts():
                    key = part.get_param('name', header='content-disposition')
                    fields[key] = part.get_payload(decode=True)
                    if key == 'file':
                        filename = part.get_filename()
                if fields.get('root') != b'gcodes' or fields.get('print') != b'false' or not filename:
                    self.respond({}, 400)
                    return
                stand.uploads.append({'filename': filename, 'print': fields['print'].decode()})
                stand.files[filename] = fields['file']
                if stand.after_upload:
                    stand.after_upload()
                if stand.fault == 'upload_timeout':
                    time.sleep(stand.response_delay)
                self.respond({'item': {'path': filename, 'root': 'gcodes'},
                              'print_started': False, 'print_queued': stand.fault == 'queued'})

        self.http_server = ThreadingHTTPServer(('127.0.0.1', http_port), Handler)
        self.ws_server = serve(self._websocket, '127.0.0.1', ws_port, max_size=1_000_000)
        self.http_url = 'http://127.0.0.1:' + str(self.http_server.server_port)
        self.ws_url = 'ws://127.0.0.1:' + str(self.ws_server.socket.getsockname()[1]) + '/websocket'
        self.threads = []

    def _websocket(self, ws):
        message = json.loads(ws.recv())
        self.start_requests.append(message)
        reply = {'jsonrpc': '2.0', 'id': message['id']}
        if self.fault == 'nested_error':
            reply['result'] = {'state': 'error', 'message': 'not ready'}
        elif self.fault == 'rpc_error':
            reply['error'] = {'code': -32601, 'message': 'method unavailable'}
        else:
            params = message['params']
            assert message['method'] == 'server.files.start_local_print'
            assert params['path'] in self.files
            self.accepted_starts.append(params)
            self.start_event.set()
            self.filename = params['path']
            self.state = 'printing'
            self.mapping = [pair[1] for pair in json.loads(params['options']['MAP_TABLE'])]
            if self.fault == 'wrong_mapping':
                self.mapping = [3, 3, 3, 3]
            if self.fault == 'invalid_mapping':
                self.mapping = [0, True, 2, 3]
            if self.fault == 'start_disconnect':
                ws.close()
                return
            if self.fault == 'start_timeout':
                time.sleep(self.response_delay)
            reply['result'] = {'state': 'success', 'filename': self.filename}
        try:
            ws.send(json.dumps(reply))
        except Exception:
            pass  # Deliberately late/lost replies in fault tests.

    def __enter__(self):
        for run in (self.http_server.serve_forever, self.ws_server.serve_forever):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def __exit__(self, *args):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.ws_server.shutdown()
        for thread in self.threads:
            thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-port', type=int, default=0)
    parser.add_argument('--ws-port', type=int, default=0)
    args = parser.parse_args()
    with MockSenderU1(http_port=args.http_port, ws_port=args.ws_port) as server:
        print(json.dumps({'http': server.http_url, 'ws': server.ws_url}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
