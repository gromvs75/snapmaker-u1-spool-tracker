"""Bench-only in-memory observer. No driver file changes or added radio commands.

Must attach with the driver quiescent. Real Klipper lifecycle integration is pending.
"""
import copy
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
        if any(not hasattr(reader, n) or not callable(getattr(reader, n)) for n in names):
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
            answer = self.stock_callback(channel, operation, result, card_type, data)
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
        def apply(_eventtime=0):
            with self.lock:
                if not self.active or generation != self.generation: return
                if seq <= self.channels[str(channel)].get('sequence', 0): return
                self.channels[str(channel)] = {'state': state, 'uid': uid, 'sequence': seq}
        try:
            self.enqueue(apply)
        except Exception:
            # No propagation into the stock driver's thread. Invalidate cached state.
            with self.lock:
                self.generation += 1
                self.channels = {str(i): {'state':'unknown','uid':None} for i in range(4)}

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
