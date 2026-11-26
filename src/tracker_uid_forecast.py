"""Read-only pre-upload forecasts. Never supplies plans to accounting."""
import copy
import logging
import math
from collections import Counter, defaultdict
from colorsys import rgb_to_hsv
from pathlib import Path
import threading
import time
from slice_identity import bed_identity
from material_guard import material_family
from slice_observer import HEX_COLOUR, SliceObserver


# Keep the close RGB match for subtle colors and hues near a category boundary.
MAX_COLOR_DISTANCE = 55
HUE_LIMITS = (
    (15, 'red'), (45, 'orange'), (75, 'yellow'), (168, 'green'),
    (205, 'cyan'), (252, 'blue'), (290, 'purple'), (345, 'pink'), (360, 'red'),
)


def rgb(color):
    if isinstance(color, str) and HEX_COLOUR.fullmatch(color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return None


def visual_color(color):
    """Group swatches by their basic visual color for a pre-print estimate."""
    hue, saturation, value = rgb_to_hsv(*(component / 255 for component in color))
    if value <= .18:
        return 'black'
    if saturation <= .15:
        return 'white' if value >= .87 else 'gray'
    if saturation < .3:
        return None
    group = next(name for limit, name in HUE_LIMITS if hue * 360 < limit)
    if group == 'orange' and value < .65:
        return 'brown'
    if group == 'red' and saturation < .55 and value >= .72:
        return 'pink'
    return group


def forecast_entry(entry, heads=(), reserve=0):
    """Estimate pre-print head usage from the slice and saved spool assignments."""
    colors = entry.get('colors', [])
    types = entry.get('filament_types', [])
    materials = [
        dict(number=i + 1, grams=weight, color=colors[i] if i < len(colors) else None)
        for i, weight in enumerate(entry.get('weights', [])) if weight > 0
    ]
    result = dict(entry, plate=entry.get('plate'), materials=materials, rows=[], status='unknown',
                  mapping_assumed=False, requires_mapping=bool(materials))
    if not heads or not materials:
        return result

    spools = {head['channel']: head['spool'] for head in heads if head['spool']}
    available = {head['channel']: head.get('forecast_usable', head['usable']) for head in heads}
    active_usage = {head['channel']: head.get('active_print_mg', 0) for head in heads}
    spool_profiles = {}
    for channel, spool in spools.items():
        details = spool.get('details', {})
        if not details.get('archived'):
            spool_profiles[channel] = (material_family(details.get('material')), rgb(details.get('color')))

    proposed = {}
    choices = {}
    for material in materials:
        index = material['number'] - 1
        family = material_family(types[index]) if index < len(types) else None
        color = rgb(material['color'])
        compatible = [channel for channel, (kind, _) in spool_profiles.items() if family and kind == family]
        swatches = [(channel, spool_profiles[channel][1]) for channel in compatible
                    if color is not None and spool_profiles[channel][1] is not None]
        group = visual_color(color) if color is not None else None
        exact = [channel for channel, spool_color in swatches if color == spool_color]
        candidates = exact or [channel for channel, spool_color in swatches
                               if math.dist(color, spool_color) <= MAX_COLOR_DISTANCE
                               or (group is not None and group == visual_color(spool_color))]
        choices[index + 1] = candidates or (compatible if family else spool_profiles)
        if len(candidates) == 1:
            proposed[index + 1] = candidates[0]

    # Competing logical profiles need a user choice, even if both match exactly.
    counts = Counter(proposed.values())
    for material in materials:
        channel = proposed.get(material['number'])
        material['channel'] = channel if counts[channel] == 1 else None

    used_spools = defaultdict(float)
    for material in materials:
        if material['channel'] is not None:
            used_spools[spools[material['channel']]['spool_id']] += material['grams']

    def estimate(channel, used, total):
        spool = spools[channel]
        current = active_usage[channel]
        remaining = max(0, spool['remaining_mg'] - current) / 1000 if available[channel] and current is not None else None
        after = remaining - total if remaining is not None else None
        deficit = max(0, round(reserve - after, 9)) if after is not None else None
        return dict(channel=channel, spool=spool, used=used, remaining=remaining, after=after,
                    deficit=deficit, unknown=remaining is None, enough=(deficit == 0),
                    active_print_g=current / 1000 if current is not None else None,
                    status='unknown' if remaining is None else 'shortage' if deficit else 'ok')

    rows = []
    for material in materials:
        channel = material['channel']
        if channel is not None:
            rows.append(estimate(channel, material['grams'], used_spools[spools[channel]['spool_id']]))
        else:
            # A choice shown here assumes this material alone on that head.
            material['choices'] = [
                {key: candidate[key] for key in ('channel', 'after', 'deficit')}
                for candidate in (estimate(ch, material['grams'], material['grams'])
                                  for ch in choices[material['number']] if counts[ch] != 1)
            ]
    mapping_needed = len(rows) != len(materials)
    status = ('shortage' if any(row['status'] == 'shortage' for row in rows)
              else 'unknown' if mapping_needed or any(row['unknown'] for row in rows)
              else 'ok')
    return dict(result, rows=rows, status=status, requires_mapping=mapping_needed,
                includes_active_print=any((row['active_print_g'] or 0) > 0 for row in rows),
                active_print_unknown=any(row['active_print_g'] is None for row in rows))


def enrich(snapshot, inventory):
    """Shared overview/tray view model. Selected plate stays a GUI-only choice."""
    entries=snapshot['entries'];latest=next((e for e in entries if e['source']==snapshot['latest']),None)
    project=str(Path(latest['source']).parent.parent) if latest else None
    current=[e for e in entries if (project is None or str(Path(e['source']).parent.parent)==project)
             and not (e.get('sha256') in inventory['accounted'] and
                      e.get('completed_at_ns',0)/1e9<=inventory['accounted'][e['sha256']])]
    ready=[e for e in current if e['state']=='ready']
    source=max(ready,key=lambda e:e['completed_at_ns'])['source'] if ready else None
    previews = [forecast_entry(entry) for entry in current]
    printers={pid:dict(p,entries=[forecast_entry(e, p['heads'], inventory['safety_margin_g']) for e in current])
              for pid,p in inventory['printers'].items()}
    selected=inventory['selected_printer']
    if selected not in printers:selected=next(iter(printers),'')
    return dict(snapshot,entries=previews,latest=source,project=project,printers=printers,
                selected_printer=selected,safety_margin_g=inventory['safety_margin_g'])


class SliceForecast:
    def __init__(self, session, default_root):
        self.session=session; self.default_root=Path(default_root)
        self.observer=None; self.root=None; self.lock=threading.Lock()
        self.value={'entries':[], 'latest':None, 'checked_at':None, 'error':''}
        self.stopped=threading.Event(); self.thread=None

    def poll(self):
        root=Path(self.session.call('settings')['values'].get('slice_root') or self.default_root).expanduser()
        if self.root!=root:
            self.root=root; self.observer=None
        if not root.is_dir():
            result=dict(entries=[],latest=None,watch_root=str(root),checked_at=time.time(),error='Каталог нарезки пока не найден.')
        else:
            if self.observer is None:self.observer=SliceObserver(root, allow_extra_profiles=True)
            self.observer.poll()
            entries=copy.deepcopy(list(self.observer.entries.values()))
            for entry in entries:
                if entry['state']=='ready' and entry.get('plate_identity', 'absent')=='absent':
                    entry['plate']=bed_identity(root/entry['source'],entry['completed_at_ns'])
                    entry['plate_identity']='project_metadata' if entry['plate'] else 'absent'
            ready=[e for e in entries if e['state']=='ready']
            latest=max(ready,key=lambda e:e['completed_at_ns'])['source'] if ready else None
            result=dict(entries=entries,latest=latest,watch_root=str(root),checked_at=time.time(),error='')
        result=enrich(result,self.session.call('forecast_inventory'))
        with self.lock:
            old=[(e['source'],e['state'],e.get('sha256')) for e in self.value['entries']]
            new=[(e['source'],e['state'],e.get('sha256')) for e in result['entries']]
            self.value=result
        if old!=new:logging.getLogger('tracker20').info('Slice observation states=%s',new)
        return result

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.value)

    def start(self):
        def run():
            while not self.stopped.is_set():
                try:self.poll()
                except Exception:
                    logging.getLogger('tracker20').exception('Slice observation failed')
                    with self.lock:self.value=dict(entries=[],latest=None,error='Наблюдение нарезки недоступно.',checked_at=time.time())
                self.stopped.wait(1)
        self.thread=threading.Thread(target=run,name='tracker20-slices');self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join()
