"""Experimental Klipper UID observer; validated on software bench only.

Install before Klipper startup. No radio commands or inventory mutations.
"""
import copy
import inspect
import logging
import sys
import time
import hashlib
import threading
import uuid
from pathlib import Path

P = '_FM175XXReader__'


def selected_uid(picc):
    count = {0: 1, 0x40: 2, 0x80: 3}.get(picc.ATQA[0] & 0xC0)
    if count is None or picc.CASCADE_LEVEL != count - 1:
        return None
    uid = []
    for i in range(count):
        block = list(picc.UID[i*4:i*4+4])
        if len(block) != 4 or any(type(v) is not int or not 0 <= v <= 255 for v in block):
            return None
        if picc.BCC[i] != block[0] ^ block[1] ^ block[2] ^ block[3]:
            return None
        more = i < count - 1
        if bool(picc.SAK[i] & 4) != more or (more and block[0] != 0x88):
            return None
        uid.extend(block[1:] if more else block)
    return uid if any(uid) and uid[0] != 8 else None


class MemoryUidBridge:
    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}
        self.local = threading.local()
        self.lock = threading.RLock()
        self.reader = None
        self.active = False
        self.generation = 0

    def attach(self, reader, *, source_path, allowed_sha256, read_op, clear_op, ok=0):
        if self.active or getattr(reader, '_tracker_uid_owner', None) is not None:
            raise ValueError('Already wrapped')
        if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() not in allowed_sha256:
            raise ValueError('Unsupported driver hash')
        names = [P+'select_channel', P+'reader_a_activate', P+'card_info_deal_cb',
                 'register_cb_2_card_info_deal']
        if any(not hasattr(reader, n) or (n != P+'card_info_deal_cb' and not callable(getattr(reader, n))) for n in names):
            raise ValueError('Driver interface unavailable')
        self.original = {n: getattr(reader, n) for n in names}
        self.instance_original = {n: (n in vars(reader), vars(reader).get(n)) for n in names}
        self.stock_callback = self.original[P+'card_info_deal_cb']
        self.reader = reader
        def select(channel):
            result = self.original[P+'select_channel'](channel)
            self.local.channel = channel
            self.local.seen = set()
            return result
        def activate():
            result = self.original[P+'reader_a_activate']()
            if result == ok:
                try:
                    uid = selected_uid(getattr(reader, P+'picc_a'))
                    if uid and hasattr(self.local, 'seen'):
                        self.local.seen.add(bytes(uid).hex().upper())
                except Exception:
                    # An observer must not turn a successful stock scan into a failure.
                    pass
            return result
        def callback(channel, operation, result, card_type, data):
            # Stock receives EXACT original arguments, including authentication failure.
            answer = self.stock_callback(channel, operation, result, card_type, data) if self.stock_callback else None
            if type(channel) is int and 0 <= channel < 4:
                if operation == clear_op:
                    self._publish(channel, 'absent', None)
                elif operation == read_op:
                    seen = getattr(self.local, 'seen', set()) if getattr(self.local, 'channel', None)==channel else set()
                    if len(seen)==1:
                        self._publish(channel, 'present', next(iter(seen)))
                    else:
                        self._publish(channel, 'conflict' if len(seen)>1 else 'unreadable', None)
            self.local.seen = set()
            return answer
        def register(cb):
            if not callable(cb):
                return self.original['register_cb_2_card_info_deal'](cb)
            self.stock_callback = cb
            return self.original['register_cb_2_card_info_deal'](callback)
        self.wrappers = dict(zip(names, [select, activate, callback, register]))
        reader._tracker_uid_owner = self
        for n, value in self.wrappers.items(): setattr(reader, n, value)
        self.active = True
        self.generation += 1

    def _publish(self, channel, state, uid):
        with self.lock:
            if not self.active: return
            generation = self.generation
            self.sequence += 1
            seq = self.sequence
            observed_at = time.monotonic()
        def apply(_eventtime=0):
            with self.lock:
                if not self.active or generation != self.generation: return
                if seq <= self.channels[str(channel)].get('sequence', 0): return
                self.channels[str(channel)] = {'state': state, 'uid': uid, 'sequence': seq, 'observed_at': observed_at}
        try:
            self.enqueue(apply)
        except Exception:
            # No propagation into the stock driver's thread. Invalidate cached state.
            with self.lock:
                self.generation += 1
                self.channels = {str(i): {'state':'unknown','uid':None} for i in range(4)}

    def suspend(self):
        # Do not replace hooks while the stock thread may still be executing.
        # Hooks remain transparent pass-through until the Klipper process exits.
        with self.lock:
            self.active = False
            self.generation += 1
            self.channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}

    def detach(self):
        if not self.active: return
        r=self.reader
        if any(getattr(r,n) is not wrapper for n,wrapper in self.wrappers.items()):
            raise ValueError('Another component replaced a hook; restart required')
        with self.lock:
            self.active=False; self.generation+=1
            self.channels={str(i):{'state':'unknown','uid':None} for i in range(4)}
        for n,(existed,value) in self.instance_original.items():
            if n == P+'card_info_deal_cb': setattr(r,n,self.stock_callback)
            elif existed: setattr(r,n,value)
            else: delattr(r,n)
        del r._tracker_uid_owner

    def get_status(self):
        with self.lock:
            return copy.deepcopy({'epoch':self.epoch,'sequence':self.sequence,'channels':self.channels})


# Exact raw source hashes from the pinned firmware corpus; no permissive override.
SUPPORTED_DRIVERS = {'c118a0ff0077d789a558f738bead5cf8e10e28a0a57bb693ba47212303c6ece6': '1.3.0.168', '68ec97fd4dab74a1fb3690f6f2c4e889abac1c2dc9eedaebb43dab2657ddd392': '2.0.0.205', 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8': '2.1.0.157'}


def _validate_methods(reader, driver_module, source):
    if type(reader) is not driver_module.FM175XXReader:
        raise ValueError('Unexpected reader class')
    # Check the loaded code against the approved source, not just the file on disk.
    compiled = compile(source.read_bytes(), str(source), 'exec')
    code_type = type(compiled)
    klass = next(c for c in compiled.co_consts if isinstance(c, code_type) and c.co_name=='FM175XXReader')
    expected = {c.co_name:c for c in klass.co_consts if isinstance(c,code_type)}
    for name in (P+'select_channel',P+'reader_a_activate','register_cb_2_card_info_deal'):
        fn = getattr(reader,name,None)
        short = name.replace(P,'__',1) if name.startswith(P) else name
        if name in vars(reader) or not inspect.ismethod(fn) or fn.__self__ is not reader:
            raise ValueError('Reader has an existing hook: '+name)
        code=fn.__func__.__code__
        wanted=expected.get(short)
        if wanted is None or code.co_code!=wanted.co_code or code.co_consts!=wanted.co_consts:
            raise ValueError('Loaded reader differs from approved source: '+name)


class TrackerUid:
    def __init__(self, config):
        self.printer=config.get_printer()
        self.reactor=self.printer.get_reactor()
        self.enabled=config.getboolean('enabled', True)
        self.stale_after=config.getfloat('stale_after', 300., minval=1.)
        self.bridge=MemoryUidBridge(self.reactor.register_async_callback)
        self.state='disabled' if not self.enabled else 'waiting'
        self.reason=''
        self.driver_version=None
        self.connected=False
        self.printer.register_event_handler('klippy:connect', self._connect)
        self.printer.register_event_handler('klippy:ready', self._ready)
        for event in ('klippy:shutdown','klippy:disconnect','klippy:connect_error','gcode:request_restart'):
            self.printer.register_event_handler(event,self._stop)
        self.printer.lookup_object('webhooks').register_endpoint('tracker_uid/status',self._status_request)

    def _connect(self):
        if not self.enabled or self.connected:
            return
        self.connected=True
        try:
            reader=self.printer.lookup_object('fm175xx_reader',None)
            if reader is None:raise ValueError('RFID reader unavailable')
            module=sys.modules[type(reader).__module__]
            source=Path(inspect.getsourcefile(module)).resolve()
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            if digest not in SUPPORTED_DRIVERS:raise ValueError('Unsupported driver hash')
            _validate_methods(reader,module,source)
            self.bridge.attach(reader,source_path=source,allowed_sha256=SUPPORTED_DRIVERS,
                               read_op=module.FM175XX_CARD_INFO_READ,
                               clear_op=module.FM175XX_CARD_INFO_CLEAR,ok=module.FM175XX_OK)
            self.driver_version=SUPPORTED_DRIVERS[digest]
            self.state='attached'
        except Exception as exc:
            self.state='unavailable';self.reason=str(exc)
            logging.warning('tracker_uid disabled: %s',exc)

    def _ready(self):
        if self.state=='attached':self.state='ready'

    def _stop(self,*args):
        self.bridge.suspend()
        self.state='stopped'
        self.reason='Klipper stopped; restart required'

    def get_status(self,eventtime=None):
        if self.bridge.active and any(getattr(self.bridge.reader,n,None) is not wrapper
                                      for n,wrapper in self.bridge.wrappers.items()):
            self.bridge.suspend()
            self.state='unavailable'
            self.reason='Reader hook changed; restart required'
        status=self.bridge.get_status()
        now=time.monotonic()
        for channel in status['channels'].values():
            observed=channel.pop('observed_at',None)
            channel['age_seconds']=max(0.,now-observed) if observed is not None else None
            if observed is not None and now-observed>self.stale_after:
                channel['state']='stale';channel['uid']=None
            channel['uid_length'] = len(channel['uid'])//2 if channel['uid'] else 0
        status.update(schema_version=1, module_version='0.1.0-bench',state=self.state,
                      reason=self.reason,driver_version=self.driver_version)
        return status

    def _status_request(self, request):
        request.send(self.get_status())


def load_config(config):
    return TrackerUid(config)
