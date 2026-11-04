"""Track RFID observations as evidence; a missing tag is not a spool ID."""
from spool_identity import tag_uid


class TagEvidence:
    def __init__(self):
        self.info = None
        self.state = None
        self.initial = None
        self.observed_nonzero = [set() for _ in range(4)]
        self.invalid = False

    def apply(self, status):
        data = status.get('filament_detect') if isinstance(status, dict) else None
        if data is None:
            return
        if not isinstance(data, dict):
            self.invalid = True
            return
        if 'info' in data:
            self.info = data['info']
        if 'state' in data:
            self.state = data['state']
        tags = self.snapshot()
        if tags is not None:
            for i, uid in enumerate(tags):
                if uid is not None:
                    self.observed_nonzero[i].add(uid)

    def snapshot(self):
        if (self.invalid or not isinstance(self.info, list) or len(self.info) != 4
                or not isinstance(self.state, list) or len(self.state) != 4
                or any(type(s) is not int or s != 0 for s in self.state)):
            return None
        result = []
        for entry in self.info:
            if not isinstance(entry, dict) or 'CARD_UID' not in entry:
                return None
            uid = entry['CARD_UID']
            if type(uid) is int and uid == 0:
                result.append(None)
            else:
                if not isinstance(uid, list):
                    return None
                try:
                    parsed = tag_uid(uid)
                    if parsed is None:
                        return None
                    result.append(parsed)
                except ValueError:
                    return None
        return result

    def for_new_job(self):
        new = TagEvidence()
        new.info, new.state, new.invalid = self.info, self.state, self.invalid
        new.initial = new.snapshot()
        if new.initial is not None:
            for i, uid in enumerate(new.initial):
                if uid is not None: new.observed_nonzero[i].add(uid)
        return new

    def report(self, feed):
        final = self.snapshot()
        same = [False] * 4
        if self.initial is not None and final is not None and not self.invalid:
            for i, (old, new) in enumerate(zip(self.initial, final)):
                # A tagged source can disappear after observed runout. A new
                # UID or insertion cannot be silently charged to the old spool.
                observed = self.observed_nonzero[i]
                same[i] = (len(observed) <= 1 and (old == new or
                    (old is not None and new is None and feed['runouts'][i])))
        return {'known': self.initial is not None and final is not None and not self.invalid,
                'unchanged': same, 'initial': self.initial, 'final': final}
