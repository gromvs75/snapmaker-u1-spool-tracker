"""Read-only pre-upload forecasts. Never supplies plans to accounting."""
import copy
import logging
from pathlib import Path
import threading
import time
from slice_identity import bed_identity
from slice_observer import SliceObserver


def forecast_entry(entry):
    """Keep Orca's material numbers until the printer reports a job's head mapping."""
    colors = entry.get('colors', [])
    materials = [
        dict(number=i + 1, grams=weight, color=colors[i] if i < len(colors) else None)
        for i, weight in enumerate(entry.get('weights', [])) if weight > 0
    ]
    return dict(entry, plate=entry.get('plate'), materials=materials, rows=[],
                status='unknown', mapping_assumed=False, requires_mapping=bool(materials))


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
    printers={pid:dict(p,entries=previews)
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
