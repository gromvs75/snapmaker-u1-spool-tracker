"""Read-only multi-printer UID client. No printer commands or accounting writes.

Transport dependency: websocket-client. Each printer owns its connection/thread.
Names are display labels; printer_id is the persistent identity, independent of IP.
"""
from dataclasses import dataclass, field
import copy
import json
import math
import re
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit


def canonical_uid(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{14}|[0-9a-fA-F]{20})', value):
        raise ValueError('Invalid UID')
    if int(value, 16) == 0 or value[:2].lower() == '08':
        raise ValueError('Nonpersistent UID')
    return value.upper()


@dataclass(frozen=True)
class PrinterEndpoint:
    printer_id: str
    name: str
    url: str
    api_key: str = field(default='', repr=False)

    def websocket_url(self):
        u = urlsplit(self.url)
        if not self.printer_id or u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('Expected HTTP(S) Moonraker URL and persistent printer_id')
        return urlunsplit(('wss' if u.scheme == 'https' else 'ws', u.netloc, u.path.rstrip('/') + '/websocket', '', ''))


def validate_status(raw):
    """Validate a FULL snapshot only. Partial notifications never replace state."""
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1:
        raise ValueError('Unsupported UID API schema')
    if not isinstance(raw.get('epoch'), str) or not raw['epoch']:
        raise ValueError('Missing epoch')
    if type(raw.get('sequence')) is not int or raw['sequence'] < 0:
        raise ValueError('Invalid sequence')
    if raw.get('state') not in ('ready', 'waiting', 'attached', 'unavailable', 'disabled', 'stopped'):
        raise ValueError('Invalid module state')
    channels = raw.get('channels')
    if not isinstance(channels, dict) or set(channels) != {'0', '1', '2', '3'}:
        raise ValueError('Expected four channels')
    result = copy.deepcopy(raw)
    for ch, c in channels.items():
        if not isinstance(c, dict) or c.get('state') not in ('unknown', 'present', 'absent', 'unreadable', 'conflict', 'stale'):
            raise ValueError('Invalid channel state')
        if c['state'] == 'present':
            result['channels'][ch]['uid'] = canonical_uid(c.get('uid'))
            age = c.get('age_seconds')
            if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0:
                raise ValueError('Invalid observation age')
            if type(c.get('sequence')) is not int or not 0 < c['sequence'] <= raw['sequence']:
                raise ValueError('Invalid observation sequence')
        elif c.get('uid') is not None:
            raise ValueError('UID on unconfirmed channel')
    return result


class UidClient:
    def __init__(self, endpoint, *, poll_interval=1., response_timeout=4., max_observation_age=300., reconnect_max=8.):
        self.session_id = uuid.uuid4().hex
        self.endpoint = endpoint
        self.url = endpoint.websocket_url()
        if min(poll_interval, response_timeout, max_observation_age, reconnect_max) <= 0:
            raise ValueError('Timeouts must be positive')
        self.poll_interval = poll_interval
        self.response_timeout = response_timeout
        self.max_observation_age = max_observation_age
        self.reconnect_max = reconnect_max
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._socket = None
        self._raw = None
        self._received = 0.
        self._state = 'stopped'
        self._generation = 0
        self._connections = 0
        self._pushes = 0
        self._successful_responses = 0

    def start(self):
        import websocket  # Fail visibly at startup if the optional dependency is missing.
        self._transport = websocket
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='uid-' + self.endpoint.printer_id, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            sock = self._socket
        if sock:
            sock.close()
        if self._thread:
            self._thread.join(self.response_timeout + 2)
            if self._thread.is_alive():
                raise RuntimeError('UID client did not stop')
        self._invalidate('stopped')

    def _invalidate(self, state):
        with self._lock:
            self._state = state
            self._raw = None
            self._received = 0.

    def _accept(self, raw):
        value = validate_status(raw)
        with self._lock:
            if self._raw and value['epoch'] == self._raw['epoch'] and value['sequence'] < self._raw['sequence']:
                raise ValueError('Out-of-order snapshot')
            self._successful_responses += 1
            self._raw = value
            self._received = time.monotonic()
            self._state = 'ready' if value['state'] == 'ready' else 'module_unavailable'

    def snapshot(self):
        with self._lock:
            state = self._state
            elapsed = time.monotonic() - self._received
            raw = copy.deepcopy(self._raw)
            if raw and elapsed > self.response_timeout + self.poll_interval:
                state = 'offline'
            channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}
            if state == 'ready' and raw:
                channels = raw['channels']
                for c in channels.values():
                    if c['state'] == 'present':
                        c['age_seconds'] += elapsed
                        if c['age_seconds'] > self.max_observation_age:
                            c.update(state='stale', uid=None)
            return dict(printer_id=self.endpoint.printer_id, name=self.endpoint.name,
                        state=state, channels=channels, epoch=raw['epoch'] if raw else None,
                        client_session=self.session_id, generation=self._generation, connections=self._connections,
                        push_notifications=self._pushes)

    def _session(self, ws):
        request_id = 0
        def rpc(method, params):
            nonlocal request_id
            request_id += 1
            ws.send(json.dumps(dict(jsonrpc='2.0', id=request_id, method=method, params=params)))
            deadline = time.monotonic() + self.response_timeout
            while not self._stop.is_set() and time.monotonic() < deadline:
                try:
                    msg = json.loads(ws.recv())
                except TimeoutError:
                    continue
                if msg.get('method') in ('notify_klippy_disconnected', 'notify_klippy_shutdown'):
                    raise ConnectionError('Klipper disconnected')
                if msg.get('method') == 'notify_status_update':
                    with self._lock: self._pushes += 1
                if msg.get('id') == request_id:
                    if 'error' in msg: raise ConnectionError('UID API not ready')
                    return msg['result']
            raise TimeoutError('UID API timeout')
        # Retrying session handles missing module / endpoint registration on startup.
        subscribed = rpc('printer.objects.subscribe', {'objects': {'tracker_uid': None}})
        self._accept(subscribed['status']['tracker_uid'])
        while not self._stop.is_set():
            result = rpc('printer.objects.query', {'objects': {'tracker_uid': None}})
            self._accept(result['status']['tracker_uid'])
            # Notifications wake the next full refresh; never merge partial deltas.
            deadline = time.monotonic() + self.poll_interval
            while not self._stop.is_set() and time.monotonic() < deadline:
                try:
                    msg = json.loads(ws.recv())
                except TimeoutError:
                    continue
                if msg.get('method') in ('notify_klippy_disconnected', 'notify_klippy_shutdown'):
                    raise ConnectionError('Klipper disconnected')
                if msg.get('method') == 'notify_status_update':
                    with self._lock: self._pushes += 1
                    break

    def _run(self):
        websocket = self._transport
        delay = .2
        while not self._stop.is_set():
            ws = None
            healthy_before = self._successful_responses
            self._invalidate('connecting')
            try:
                headers = {'X-Api-Key': self.endpoint.api_key} if self.endpoint.api_key else {}
                ws = websocket.create_connection(self.url, timeout=self.response_timeout, header=headers)
                # Normalize the transport's timeout exception for the session loop.
                original_recv = ws.recv
                def recv():
                    try: return original_recv()
                    except websocket.WebSocketTimeoutException as exc: raise TimeoutError() from exc
                ws.recv = recv
                ws.settimeout(min(.2, self.poll_interval))
                with self._lock:
                    self._socket = ws
                    self._generation += 1
                    self._connections += 1
                self._session(ws)
            except Exception:
                self._invalidate('offline')
            finally:
                if ws: ws.close()
                with self._lock: self._socket = None
            if self._successful_responses > healthy_before:
                delay = .2
            if self._stop.wait(delay): break
            delay = min(self.reconnect_max, delay * 2)
        self._invalidate('stopped')


class UidFleet:
    def __init__(self, endpoints, **options):
        endpoints = list(endpoints)
        if len({e.printer_id for e in endpoints}) != len(endpoints):
            raise ValueError('Duplicate printer_id')
        if len({e.websocket_url() for e in endpoints}) != len(endpoints):
            raise ValueError('Duplicate printer endpoint')
        self.clients = {e.printer_id: UidClient(e, **options) for e in endpoints}

    def start(self):
        for c in self.clients.values(): c.start()

    def stop(self):
        for c in self.clients.values(): c.stop()

    def snapshot(self):
        return {pid: c.snapshot() for pid, c in self.clients.items()}
