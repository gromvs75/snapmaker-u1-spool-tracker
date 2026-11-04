"""Tracker direct-send alpha: HTTP upload + WebSocket start, loopback only.

Explicit test inventory and ledger required. No default app store or monitor.
Uncertain network outcomes are durable and NEVER automatically retried.
"""
import argparse
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from presend import decode_json, digest, fingerprint, validate_request
from tool_mapping import validate_mapping

MAX_FILE = 32 * 1024 * 1024


class SendError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SendError('Redirect refused')


def read_bounded(path):
    with open(path, 'rb') as file:
        data = file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise SendError('Alpha file limit: 32 MiB')
    return data


class LocalTransport:
    """Real HTTP/WS transport restricted to literal 127.0.0.1, no proxies."""
    def __init__(self, http_url, ws_url, timeout=2):
        for url, scheme in ((http_url, 'http'), (ws_url, 'ws')):
            p = urlsplit(url)
            if (p.scheme != scheme or p.hostname != '127.0.0.1' or not p.port
                    or p.username or p.password or p.query or p.fragment
                    or p.path not in ('', '/', '/websocket')):
                raise SendError('This alpha permits only explicit loopback test endpoints')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise SendError('Invalid timeout')
        self.http = http_url.rstrip('/')
        self.ws = ws_url
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _http(self, path, data=None, headers=None, limit=MAX_FILE):
        req = Request(self.http + path, data=data, headers=headers or {})
        with self.opener.open(req, timeout=self.timeout) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise SendError('Oversized response')
        return raw

    def _json(self, path, data=None, headers=None):
        result = decode_json(self._http(path, data, headers, 1_000_000))
        if not isinstance(result, dict) or 'error' in result or 'result' not in result:
            raise SendError('Invalid Moonraker response')
        return result['result']

    def status(self):
        result = self._json('/printer/objects/query?webhooks&print_stats&print_task_config')
        return result['status']

    def ready(self):
        status = self.status()
        if (status['webhooks']['state'] != 'ready'
                or status['print_stats']['state'] not in ('standby', 'complete', 'cancelled')
                or status['print_task_config'].get('auto_replenish_filament') is not False):
            raise SendError('Printer not ready, busy, or automatic replenishment unknown/enabled')

    def upload(self, name, data):
        boundary = 'tracker-' + uuid.uuid4().hex
        parts = []
        for key, value in (('root', 'gcodes'), ('print', 'false')):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        body = b''.join(parts) + data + f'\r\n--{boundary}--\r\n'.encode()
        result = self._json('/server/files/upload', body, {'Content-Type': 'multipart/form-data; boundary=' + boundary})
        if (result.get('print_started') is not False or result.get('print_queued') is not False
                or result.get('item', {}).get('path') != name
                or result.get('item', {}).get('root') != 'gcodes'):
            raise SendError('Upload did not confirm an unqueued, nonprinting file')

    def verify(self, name, data):
        meta = self._json('/server/files/metadata?' + urlencode({'filename': name}))
        if type(meta.get('size')) is not int or meta['size'] != len(data):
            raise SendError('Uploaded size mismatch')
        if self._http('/server/files/gcodes/' + name) != data:
            raise SendError('Uploaded bytes mismatch')

    def start(self, name, mapping):
        from websockets.sync.client import connect
        rpc_id = uuid.uuid4().hex
        message = {'jsonrpc': '2.0', 'id': rpc_id, 'method': 'server.files.start_local_print',
                   'params': {'path': name, 'print_plate': 1,
                              'options': {'MAP_TABLE': json.dumps(list(enumerate(mapping)), separators=(',', ':'))}}}
        # No reconnect/retry. Connection errors are conservatively uncertain too.
        with connect(self.ws, proxy=None, open_timeout=self.timeout, close_timeout=.1,
                     max_size=1_000_000) as ws:
            ws.send(json.dumps(message))
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Start response timed out')
                response = decode_json(ws.recv(timeout=remaining))
                if not isinstance(response, dict):
                    raise SendError('Invalid RPC response')
                if 'id' not in response:  # bounded wait for notifications
                    continue
                if response['id'] != rpc_id or response.get('jsonrpc') != '2.0':
                    raise SendError('Unrelated RPC response')
                if 'error' in response or response.get('result', {}).get('state') != 'success':
                    raise SendError('Start not confirmed: ' + json.dumps(response))
                if response['result'].get('filename') != name:
                    raise SendError('Start filename mismatch')
                break
        status = self.status()
        if (status['print_stats']['state'] != 'printing' or status['print_stats'].get('filename') != name
                or validate_mapping(status['print_task_config'].get('extruder_map_table')) != mapping
                or status['print_task_config'].get('auto_replenish_filament') is not False):
            raise SendError('Active job or mapping not confirmed')


class Ledger:
    """SQLite claim/reservation survives restart. One unresolved job per inventory.

    No manual release or completion API in this alpha: unresolved entries require
    investigation. Do not delete/replace a ledger to retry an uncertain operation.
    """
    def __init__(self, path):
        self.path = Path(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, inventory TEXT, state TEXT, manifest TEXT, reason TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def claim(self, job_id, inventory, manifest):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM jobs WHERE id=?', (job_id,)).fetchone():
                raise SendError('Request already recorded; no retry')
            if db.execute("SELECT 1 FROM jobs WHERE inventory=? AND state NOT IN ('blocked','sent')", (inventory,)).fetchone():
                raise SendError('Inventory has an unresolved/reserved job')
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', (job_id, inventory, 'checking', json.dumps(manifest), ''))

    def set(self, job_id, state, reason=''):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?, reason=? WHERE id=?', (state, reason, job_id))

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT state, reason, manifest FROM jobs WHERE id=?', (job_id,)).fetchone()
        return None if row is None else {'state': row[0], 'reason': row[1], 'manifest': json.loads(row[2])}


def strict_check(snapshot, timeout, checker_command=None):
    command = checker_command or ([sys.executable, '--presend-worker'] if getattr(sys, 'frozen', False)
                                 else [sys.executable, str(Path(__file__).with_name('presend.py'))])
    if not isinstance(command, (list, tuple)):
        raise SendError('Checker must be an argument list')
    with tempfile.TemporaryDirectory(prefix='tracker-check-') as folder:
        path = Path(folder) / 'request.json'
        path.write_text(json.dumps(snapshot))
        result = subprocess.run([*command, '--request', str(path)], capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise SendError('Strict checker denied or failed: ' + str(result.returncode))
    response = decode_json(result.stdout)
    if (response.get('decision') != 'allow' or type(response.get('version')) is not int
            or response['version'] != 1 or response.get('request_fingerprint') != fingerprint(snapshot)
            or response.get('sha256') != snapshot['sha256']
            or response.get('inventory_sha256') != digest(read_bounded(snapshot['inventory_path']))):
        raise SendError('Invalid checker permission')


def send(request, transport, ledger, checker_timeout=2, checker_command=None):
    """One attempt only. Explicit inventory/ledger; never writes inventory itself."""
    claimed = False
    phase = 'checking'
    try:
        if type(checker_timeout) not in (int, float) or not math.isfinite(checker_timeout) or checker_timeout <= 0:
            raise SendError('Invalid checker timeout')
        original = decode_json(json.dumps(request))
        validate_request(original)
        original['inventory_path'] = str(Path(original['inventory_path']).resolve())
        data = read_bounded(original['gcode_path'])
        inventory = read_bounded(original['inventory_path'])
        if digest(data) != original['sha256']:
            raise SendError('Source hash changed')
        name = 'tracker-' + uuid.uuid4().hex + '.gcode'
        manifest = dict(original, remote_name=name, inventory_sha256=digest(inventory),
                        http_endpoint=transport.http, ws_endpoint=transport.ws)
        ledger.claim(original['request_id'], original['inventory_path'], manifest)
        claimed = True
        with tempfile.TemporaryDirectory(prefix='tracker-send-') as folder:
            source = Path(folder) / 'checked.gcode'
            source.write_bytes(data)
            stock = Path(folder) / 'inventory.json'
            stock.write_bytes(inventory)
            snapshot = dict(original, gcode_path=str(source), inventory_path=str(stock))
            strict_check(snapshot, checker_timeout, checker_command)
            def unchanged():
                # The original caller's parameters, files and inventory must stay fixed.
                current = decode_json(json.dumps(request))
                current['inventory_path'] = str(Path(current['inventory_path']).resolve())
                if (current != original or read_bounded(original['gcode_path']) != data
                        or read_bounded(original['inventory_path']) != inventory):
                    raise SendError('Job or inventory changed')
            unchanged()
            transport.ready()
            phase = 'upload_requested'
            ledger.set(original['request_id'], phase)
            transport.upload(name, data)
            phase = 'uploaded'
            ledger.set(original['request_id'], phase)
            transport.verify(name, data)
            unchanged()
            if original['action'] == 'send':
                ledger.set(original['request_id'], 'sent')
                return ledger.get(original['request_id'])
            strict_check(snapshot, checker_timeout, checker_command)
            transport.ready()
            transport.verify(name, data)
            unchanged()
            # Durable exclusive inventory claim is retained until resolution.
            phase = 'start_requested'
            ledger.set(original['request_id'], phase)
            transport.start(name, original['mapping'])
            ledger.set(original['request_id'], 'active')
            return ledger.get(original['request_id'])
    except Exception as exc:
        state = {'checking': 'blocked', 'upload_requested': 'upload_unknown',
                 'uploaded': 'uploaded_blocked', 'start_requested': 'outcome_unknown'}[phase]
        if claimed:
            ledger.set(original['request_id'], state, str(exc))
        return {'state': state, 'reason': str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--http', required=True)
    parser.add_argument('--ws', required=True)
    parser.add_argument('--timeout', type=float, default=2)
    args = parser.parse_args()
    try:
        transport = LocalTransport(args.http, args.ws, args.timeout)
        result = send(decode_json(args.request.read_bytes()), transport, Ledger(args.ledger))
    except Exception as exc:
        result = {'state': 'blocked', 'reason': str(exc)}
    print(json.dumps(result))
    return 0 if result['state'] in ('sent', 'active') else 23



def start_uploaded(job_id, transport, ledger, checker_timeout=2):
    """Explicit start of an already verified upload; never upload a second copy."""
    phase = 'uploaded'
    claimed = False
    try:
        with ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT inventory,state,manifest FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row[1] != 'sent':
                raise SendError('Only a verified uploaded job can be started once')
            if db.execute("SELECT 1 FROM jobs WHERE inventory=? AND id<>? AND state NOT IN ('blocked','sent')", (row[0], job_id)).fetchone():
                raise SendError('Inventory has an unresolved/reserved job')
            manifest = json.loads(row[2])
            if manifest['http_endpoint'] != transport.http or manifest['ws_endpoint'] != transport.ws:
                raise SendError('Destination changed')
            db.execute('UPDATE jobs SET state=? WHERE id=?', ('preparing_start', job_id))
        claimed = True
        keys = ('version','request_id','context_id','device_id','mapping','gcode_path','inventory_path','sha256')
        request = {key: manifest[key] for key in keys}
        request['action'] = 'print'
        data = read_bounded(request['gcode_path'])
        inventory = read_bounded(request['inventory_path'])
        if digest(data) != request['sha256'] or digest(inventory) != manifest['inventory_sha256']:
            raise SendError('File or inventory changed since upload')
        strict_check(request, checker_timeout)
        transport.ready()
        transport.verify(manifest['remote_name'], data)
        if read_bounded(request['inventory_path']) != inventory or read_bounded(request['gcode_path']) != data:
            raise SendError('File or inventory changed during check')
        phase = 'start_requested'
        ledger.set(job_id, phase)
        transport.start(manifest['remote_name'], request['mapping'])
        ledger.set(job_id, 'active')
        return ledger.get(job_id)
    except Exception as exc:
        state = 'outcome_unknown' if phase == 'start_requested' else 'uploaded_blocked'
        if claimed:
            ledger.set(job_id, state, str(exc))
        return {'state': state, 'reason': str(exc)}


if __name__ == '__main__':
    sys.exit(main())
