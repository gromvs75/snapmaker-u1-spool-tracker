"""Optional Spoolman client and durable, conservative consumption outbox.

No printer controls, automatic write retries, credentials, or implicit migration.
"""
import copy
import hashlib
import json
import math
import threading
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from filelock import FileLock, Timeout


def endpoint(value):
    if not isinstance(value, str):
        raise ValueError('Spoolman URL required')
    p = urlsplit(value.strip())
    if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
            or p.query or p.fragment or any(c.isspace() for c in value)
            or p.path.rstrip('/').endswith('/api/v1')):
        raise ValueError('Use the server base URL without credentials, query or /api/v1')
    _ = p.port
    return value.strip().rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Spoolman redirects are not supported; use its final address')


class Client:
    def __init__(self, url):
        self.url = endpoint(url)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None):
        req = Request(self.url + '/api/v1' + path,
                      data=None if body is None else json.dumps(body, allow_nan=False).encode(),
                      headers={'Content-Type': 'application/json'}, method=method)
        try:
            with self.opener.open(req, timeout=5) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('Spoolman response too large')
                return json.loads(raw), response.headers
        except HTTPError as exc:
            # Never include response bodies, credentials or the server URL in errors.
            raise ValueError('Spoolman HTTP %d' % exc.code) from None

    def catalog(self):
        info, _ = self.request('GET', '/info')
        if info.get('version') != '0.27.1':
            raise ValueError('This test build supports Spoolman 0.27.1 only')
        result = {}
        for offset in range(0, 10000, 100):
            rows, headers = self.request('GET', '/spool?allow_archived=true&limit=100&offset=%d' % offset)
            if not isinstance(rows, list):
                raise ValueError('Invalid spool catalog')
            for row in rows:
                item = catalog_item(row)
                if str(item['id']) in result:
                    raise ValueError('Catalog changed during paging; refresh again')
                result[str(item['id'])] = item
            total = headers.get('X-Total-Count')
            if len(rows) < 100 or (total is not None and len(result) >= int(total)):
                return result
        raise ValueError('Catalog exceeds 10000 spools')


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid Spoolman weight')
    return float(value)


def catalog_item(row):
    if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
        raise ValueError('Invalid Spoolman spool ID')
    f = row.get('filament', {})
    name = str(f.get('name') or 'Spool').strip() or 'Spool'
    vendor = f.get('vendor')
    brand = vendor.get('name') if isinstance(vendor, dict) else None
    brand = brand.strip() if isinstance(brand, str) else ''
    # Spoolman stores the manufacturer separately from the filament name.
    # Some catalogs already include it; preserve those names without repetition.
    if brand and not (name.casefold() == brand.casefold()
                      or name.casefold().startswith(brand.casefold() + ' ')):
        name = brand + ' ' + name
    color = f.get('color_hex', '')
    remaining = row.get('remaining_weight')
    return {'id': row['id'], 'name': name[:100],
            'material': str(f.get('material') or 'Unknown')[:100],
            'remaining_g': None if remaining is None else number(remaining),
            'archived': bool(row.get('archived', False)),
            'color': '#' + color.lower() if len(color) == 6 and all(c in '0123456789abcdefABCDEF' for c in color) else None}


def blank():
    return {'url': '', 'mode': 'off', 'epoch': '', 'catalog': {}, 'checked_at': 0,
            'error': '', 'outbox': {}}


def validate(state):
    if not isinstance(state, dict) or set(state) != set(blank()):
        raise ValueError('Invalid Spoolman state')
    if state['url']:
        endpoint(state['url'])
    if state['mode'] not in ('off', 'read', 'send') or not isinstance(state['epoch'], str):
        raise ValueError('Invalid Spoolman mode')
    if state['mode'] != 'off' and (not state['url'] or not state['epoch']):
        raise ValueError('Incomplete Spoolman connection')
    number(state['checked_at'])
    if not isinstance(state['error'], str) or not isinstance(state['catalog'], dict) or not isinstance(state['outbox'], dict):
        raise ValueError('Invalid Spoolman catalog or queue')
    for sid, item in state['catalog'].items():
        if str(item['id']) != sid or type(item['id']) is not int or item['id'] <= 0:
            raise ValueError('Invalid cached ID')
        if item['remaining_g'] is not None:
            number(item['remaining_g'])
        if not isinstance(item['name'], str) or not isinstance(item['material'], str) or type(item['archived']) is not bool:
            raise ValueError('Invalid cached spool')
    for key, op in state['outbox'].items():
        if (not isinstance(key, str) or not isinstance(op, dict)
                or op.get('state') not in ('pending', 'sending', 'uncertain', 'sent', 'external', 'resolved')
                or not isinstance(op.get('job'), str) or not isinstance(op.get('local_id'), str)
                or type(op.get('spool_id')) is not int or op['spool_id'] <= 0):
            raise ValueError('Invalid Spoolman operation')
        endpoint(op['url'])
        number(op['grams'])
        number(op['created_at'])
    return copy.deepcopy(state)


def remote_id(url, sid):
    return 'sm_' + hashlib.sha256(url.encode()).hexdigest()[:16] + '_' + str(sid)


def unavailable(db, sid, now=None):
    spool = db['spools'].get(sid, {})
    if not spool.get('spoolman'):
        return False
    state = db.get('spoolman', blank())
    ref = spool['spoolman']
    item = state['catalog'].get(str(ref['id']))
    return (state['mode'] == 'off' or ref['url'] != state['url'] or bool(state['error'])
            or (time.time() if now is None else now) - state['checked_at'] > 60
            or item is None or item['archived'] or item['remaining_g'] is None
            or any(op['local_id'] == sid and op['state'] in ('pending', 'sending', 'uncertain')
                   for op in state['outbox'].values()))


def book(db, job, amounts):
    """Called inside the same Store transaction as the committed print status."""
    state = db.get('spoolman', blank())
    for sid, grams in amounts.items():
        number(grams)
        ref = db['spools'][sid].get('spoolman')
        if ref and (state['mode'] == 'off' or ref['url'] != state['url']
                    or db['runs'][job].get('spoolman_epoch') != state['epoch']):
            raise ValueError('Spoolman connection changed since print start; review required')
    for sid, grams in amounts.items():
        spool = db['spools'][sid]
        ref = spool.get('spoolman')
        if not ref:
            spool['remaining_g'] = round(max(0, spool['remaining_g'] - grams), 3)
        elif grams > 0:
            key = hashlib.sha256((job + '\0' + sid).encode()).hexdigest()
            if key in state['outbox']:
                raise ValueError('Spoolman operation already recorded')
            state['outbox'][key] = {'job': job, 'local_id': sid, 'url': ref['url'],
                'spool_id': ref['id'], 'grams': grams, 'created_at': time.time(),
                'state': 'pending' if state['mode'] == 'send' else 'external'}


class WorkerLockUnavailable(RuntimeError):
    """Another process owns the inventory worker lock."""


class Bridge:
    def __init__(self, store, client_factory=Client):
        self.store, self.client_factory = store, client_factory
        self.stop_event = threading.Event()
        self.mutex = threading.RLock()
        self.thread = None
        self.process_lock = FileLock(str(store.directory / 'spoolman-worker.lock'), timeout=0)

    def configure(self, url, mode, sole_sender=False):
        if mode not in ('off', 'read', 'send'):
            raise ValueError('Invalid mode')
        url = endpoint(url) if mode != 'off' else ''
        if mode == 'send' and sole_sender is not True:
            raise ValueError('Confirm Tracker is the only usage sender for this U1')
        with self.mutex:
            def change(db):
                state = db.get('spoolman', blank())
                restoring = state['mode'] == 'off' and url == state['url'] and mode != 'off'
                if any(x['state'] in ('pending', 'sending', 'uncertain') for x in state['outbox'].values()) and not restoring:
                    raise ValueError('Resolve queued consumption before changing connection')
                if db['monitor']['state'] in ('printing', 'paused') or any(r['status'] == 'active' for r in db['runs'].values()):
                    raise ValueError('Wait until printing ends before changing connection')
                if mode == 'off' and any(s.get('spoolman') for s in db['spools'].values()):
                    raise ValueError('Detach external spools first; their balances will not be imported automatically')
                if state['url'] and url and state['url'] != url and any(s.get('spoolman') for s in db['spools'].values()):
                    raise ValueError('Detach external spools before switching servers')
                state.update(url=url, mode=mode, epoch=uuid.uuid4().hex, catalog={}, checked_at=0, error='')
                db['spoolman'] = state
            self.store.update(change)
        if mode != 'off':
            self.refresh()

    def refresh(self):
        with self.mutex:
            state = self.store.read().get('spoolman', blank())
            if state['mode'] == 'off':
                return
            try:
                catalog = self.client_factory(state['url']).catalog()
            except Exception as exc:
                def fail(db):
                    db['spoolman']['error'] = str(exc)[:160] if isinstance(exc, ValueError) else 'Spoolman unavailable'
                self.store.update(fail)
                return
            def apply(db):
                current = db['spoolman']
                if current['epoch'] != state['epoch']:
                    return
                current.update(catalog=catalog, checked_at=time.time(), error='')
                for spool in db['spools'].values():
                    ref = spool.get('spoolman')
                    if not ref or ref['url'] != state['url']:
                        continue
                    item = catalog.get(str(ref['id']))
                    if item and not item['archived'] and item['remaining_g'] is not None:
                        spool.update(name='[Spoolman #%d] %s' % (item['id'], item['name']),
                                     material=item['material'], remaining_g=item['remaining_g'])
                        if item['color']:
                            spool['color'] = item['color']
            self.store.update(apply)

    def attach(self, sid, slot):
        if type(sid) is not int or type(slot) is not int or slot not in range(4):
            raise ValueError('Choose a spool and T0–T3')
        with self.mutex:
            self.refresh()
            def change(db):
                state = db.get('spoolman', blank())
                item = state['catalog'].get(str(sid))
                if state['mode'] == 'off' or state['error'] or not item or item['archived'] or item['remaining_g'] is None:
                    raise ValueError('Fresh available spool required')
                if db['monitor']['state'] in ('printing', 'paused'):
                    raise ValueError('Do not change spools during a print')
                local_id = remote_id(state['url'], sid)
                if any(db['slots'][str(i+1)] == local_id for i in range(4) if i != slot):
                    raise ValueError('One physical spool cannot be assigned to two heads')
                previous = db['spools'].get(local_id, {})
                if any(op['local_id'] == local_id and op['state'] in ('pending', 'sending', 'uncertain')
                       for op in state['outbox'].values()):
                    raise ValueError('Resolve usage before assigning this spool')
                db['spools'][local_id] = {'name': '[Spoolman #%d] %s' % (sid, item['name']),
                    'material': item['material'], 'remaining_g': item['remaining_g'],
                    'spoolman': {'url': state['url'], 'id': sid}}
                if 'calibration' in previous:
                    db['spools'][local_id]['calibration'] = previous['calibration']
                if item['color']:
                    db['spools'][local_id]['color'] = item['color']
                db['slots'][str(slot+1)] = local_id
            self.store.update(change)

    def recover(self):
        def change(db):
            for op in db.get('spoolman', blank())['outbox'].values():
                if op['state'] == 'sending':
                    op['state'] = 'uncertain'
        self.store.update(change)

    def detach(self, sid):
        with self.mutex:
            def change(db):
                spool = db['spools'].get(sid)
                if not spool or not spool.get('spoolman'):
                    raise ValueError('Unknown external spool')
                if db['monitor']['state'] in ('printing', 'paused') or any(r['status'] == 'active' for r in db['runs'].values()):
                    raise ValueError('Wait until printing ends')
                if any(op['local_id'] == sid and op['state'] in ('pending', 'sending', 'uncertain')
                       for op in db['spoolman']['outbox'].values()):
                    raise ValueError('Resolve usage before detaching this spool')
                del db['spools'][sid]
                for slot, assigned in db['slots'].items():
                    if assigned == sid:
                        db['slots'][slot] = ''
            self.store.update(change)

    def send_one(self):
        with self.mutex:
            state = self.store.read().get('spoolman', blank())
            if state['mode'] != 'send':
                return
            # Stop the whole queue at uncertainty, avoiding cascading ambiguous balances.
            if any(op['state'] in ('sending', 'uncertain') for op in state['outbox'].values()):
                return
            pair = next(((k, v) for k, v in state['outbox'].items() if v['state'] == 'pending'), None)
            if not pair:
                return
            key, op = pair
            # Safe read before claiming: definite server unavailability leaves pending.
            try:
                row, _ = self.client_factory(op['url']).request('GET', '/spool/%d' % op['spool_id'])
                item = catalog_item(row)
                if item['archived'] or item['remaining_g'] is None:
                    return
            except Exception:
                return
            claimed = False
            def claim(db):
                nonlocal claimed
                current = db['spoolman']
                if current['mode'] == 'send' and current['epoch'] == state['epoch'] and current['outbox'][key]['state'] == 'pending':
                    current['outbox'][key]['state'] = 'sending'
                    claimed = True
            self.store.update(claim)
            if not claimed:
                return
            result = 'uncertain'
            try:
                reply, _ = self.client_factory(op['url']).request('PUT', '/spool/%d/use' % op['spool_id'], {'use_weight': op['grams']})
                parsed = catalog_item(reply)
                if parsed['id'] == op['spool_id']:
                    result = 'sent'
            except Exception:
                pass  # Includes HTTP failures: never infer that a write did not happen.
            self.store.update(lambda db: db['spoolman']['outbox'][key].update(state=result))
            self.refresh()

    def resolve(self, key, action, note):
        if action not in ('applied', 'not_applied', 'cancel') or not isinstance(note, str) or not note.strip():
            raise ValueError('Resolution and a verification note are required')
        with self.mutex:
            def change(db):
                op = db['spoolman']['outbox'].get(key)
                if not op or op['state'] not in ('uncertain', 'pending'):
                    raise ValueError('Operation does not need resolution')
                if action == 'not_applied' and db['spoolman']['mode'] != 'send':
                    raise ValueError('Reconnect in sending mode first')
                op.update(state={'applied': 'sent', 'not_applied': 'pending', 'cancel': 'resolved'}[action],
                          resolution=action, note=note.strip()[:500])
            self.store.update(change)
            self.refresh()

    def start(self):
        self.store.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.process_lock.acquire()  # One worker per local inventory.
        except Timeout as exc:
            raise WorkerLockUnavailable(str(self.process_lock.lock_file)) from exc
        self.recover()
        def run():
            while not self.stop_event.is_set():
                try:
                    self.refresh()
                    self.send_one()
                except Exception:
                    pass
                self.stop_event.wait(15)
        self.thread = threading.Thread(target=run, daemon=True, name='spoolman')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=20)
        if not self.thread or not self.thread.is_alive():
            self.process_lock.release()
