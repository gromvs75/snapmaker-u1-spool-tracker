"""Inventory-backed slice forecasts; never modifies inventory or contacts printers."""
import copy
import re
import threading
from pathlib import Path

STOCK = (100, 50, 25, 110)

def forecast_entry(entry, stock=STOCK, inventory=None):
    index = re.search(r'\.(\d+)\.gcode$', entry['source'])
    if inventory is None:
        inventory = {'slots': {str(i+1): str(i) for i in range(4)},
                     'spools': {str(i): {'name': f'Тестовая PLA {i+1}', 'remaining_g': stock[i]}
                                for i in range(4)}, 'safety_margin_g': 5}
    slots, spools = inventory['slots'], inventory['spools']
    totals = {}
    for i, used in enumerate(entry['weights']):
        sid = slots.get(str(i+1))
        if sid:
            totals[sid] = totals.get(sid, 0) + used
    rows = []
    for i, used in enumerate(entry['weights']):
        sid = slots.get(str(i+1))
        spool = spools.get(sid)
        remaining = spool['remaining_g'] if spool else 0
        required = totals.get(sid, used)
        rows.append({'tool': f'T{i}', 'spool_id': sid,
                     'name': spool['name'] if spool else 'Катушка не назначена',
                     'used': used, 'remaining': remaining,
                     'after': round(remaining-required, 3),
                     'enough': used == 0 or bool(spool and remaining >= required + inventory['safety_margin_g'])})
    return dict(entry, rows=rows, shortage=any(not r['enough'] for r in rows),
                label=f"Пластина {int(index[1])+1 if index else '?'}")


class ForecastState:
    def __init__(self, stock=STOCK, store=None):
        self.store = store
        self.stock = tuple(stock)
        self.entries = {}
        self.latest = None
        self.revision = 0
        self.error = ''
        self.lock = threading.Lock()

    def accept(self, events):
        # Completed results only. Pending/cancelled slicing does not reserve or debit.
        with self.lock:
            for event in events:
                self.entries.pop(event['source'], None)
                self.entries[event['source']] = copy.deepcopy(event)
            if self.entries:
                self.latest = max(self.entries, key=lambda key: (self.entries[key].get('completed_at_ns', self.entries[key].get('observed_at', 0)*1e9), list(self.entries).index(key)))
            if events:
                self.revision += 1
            self.error = ''

    def snapshot(self):
        inventory = self.store.read() if self.store is not None else None
        with self.lock:
            project = str(Path(self.latest).parent.parent) if self.latest else None
            current = [e for e in sorted(self.entries.values(), key=lambda e: e['source']) if str(Path(e['source']).parent.parent) == project]
            return copy.deepcopy({'entries': [forecast_entry(e, self.stock, inventory) for e in current],
                                  'latest': self.latest, 'project': project,
                                  'safety_margin_g': inventory['safety_margin_g'] if inventory is not None else 5,
                                  'revision': self.revision, 'error': self.error,
                                  'mapping': [0, 1, 2, 3], 'mapping_assumed': True})
