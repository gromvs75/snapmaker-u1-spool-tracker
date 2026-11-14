"""Synthetic source contract and fail-closed receiver. Never authorizes debit.

Only the marked bench uses this protocol. U1 does not supply these guarantees.
A barrier certifies emitted command coverage, not counter inclusion or mass.
"""
import copy
import math
import uuid

CLOCK = 'synthetic-command-clock'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class Source:
    def __init__(self):
        self.epoch = uuid.uuid4().hex
        self.packets = []
        self.pending = set()
        self.barriers = {}
        self.sealed = float('-inf')

    def packet(self, head, start, end, length, delayed=False):
        if (type(head) is not int or head not in range(4) or
                not all(finite(v) for v in (start, end, length)) or
                start < self.sealed or end <= start):
            raise ValueError('Invalid packet or movement before sealed fence')
        p = dict(epoch=self.epoch, clock=CLOCK, seq=len(self.packets)+1,
                 head=head, start=start, end=end, length=length)
        self.packets.append(p)
        if delayed:
            self.pending.add(p['seq'])
        return copy.deepcopy(p)

    def flush(self):
        packets = [copy.deepcopy(p) for p in self.packets if p['seq'] in self.pending]
        self.pending.clear()
        return packets

    def barrier(self, key, fence):
        if not isinstance(key, str) or not key or not finite(fence):
            raise ValueError('Invalid barrier')
        if key in self.barriers:
            if self.barriers[key]['fence'] != fence:
                raise ValueError('Conflicting barrier retry')
            return copy.deepcopy(self.barriers[key])
        if fence <= self.sealed or self.pending or any(p['end'] > fence for p in self.packets):
            raise ValueError('Unsettled source fence')
        b = dict(id=key, epoch=self.epoch, clock=CLOCK, fence=fence,
                 last_seq=len(self.packets), heads=[0, 1, 2, 3])
        self.barriers[key] = b
        self.sealed = fence
        return copy.deepcopy(b)


class Receiver:
    def __init__(self, epoch):
        if not isinstance(epoch, str) or not epoch:
            raise ValueError('Fresh source epoch required')
        self.epoch = epoch
        self.packets = {}
        self.barriers = {}
        self.failure = None

    def reject(self, reason):
        self.failure = reason
        raise ValueError(reason)

    def disconnect(self):
        self.failure = 'Connection continuity lost; fresh capture required'

    def common(self, value):
        if self.failure:
            raise ValueError(self.failure)
        if value.get('epoch') != self.epoch or value.get('clock') != CLOCK:
            self.reject('Clock or epoch mismatch')

    def packet(self, p):
        self.common(p)
        seq = p.get('seq')
        if (type(seq) is not int or seq < 1 or type(p.get('head')) is not int or
                p['head'] not in range(4) or
                not all(finite(p.get(k)) for k in ('start', 'end', 'length')) or
                p['end'] <= p['start']):
            self.reject('Invalid packet')
        if seq in self.packets:
            if self.packets[seq] != p:
                self.reject('Conflicting packet replay')
            return
        for old in self.packets.values():
            if p['head'] == old['head'] and p['start'] < old['end'] and p['end'] > old['start']:
                self.reject('Overlapping packets')
        self.packets[seq] = copy.deepcopy(p)
        self.validate_fences()

    def barrier(self, b):
        self.common(b)
        if (not isinstance(b.get('id'), str) or not b['id'] or
                type(b.get('last_seq')) is not int or b['last_seq'] < 0 or
                not finite(b.get('fence')) or b.get('heads') != [0, 1, 2, 3]):
            self.reject('Invalid barrier scope')
        key = b['id']
        if key in self.barriers and self.barriers[key] != b:
            self.reject('Conflicting barrier replay')
        for old in self.barriers.values():
            if ((b['fence'] == old['fence'] and b['last_seq'] != old['last_seq']) or
                    (b['fence'] > old['fence'] and b['last_seq'] < old['last_seq']) or
                    (b['fence'] < old['fence'] and b['last_seq'] > old['last_seq'])):
                self.reject('Nonmonotonic barrier coverage')
        self.barriers[key] = copy.deepcopy(b)
        self.validate_fences()

    def validate_fences(self):
        for b in self.barriers.values():
            for seq, p in self.packets.items():
                if (seq <= b['last_seq'] and p['end'] > b['fence'] or
                        seq > b['last_seq'] and p['start'] < b['fence']):
                    self.reject('Motion crosses certified fence')

    def result(self, key):
        b = self.barriers.get(key)
        covered = b is not None and all(i in self.packets for i in range(1, b['last_seq']+1))
        return dict(boundary_proven=bool(covered and not self.failure),
                    reason=self.failure or ('Complete synthetic prefix' if covered else 'Missing barrier or packets'),
                    authorizes_debit=False, counter_scope_proven=False)
