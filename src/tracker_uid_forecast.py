"""Read-only pre-upload forecasts. Never supplies plans to accounting."""
import copy
import logging
from pathlib import Path
import threading
import time
import re
from slice_observer import SliceObserver


def forecast_entry(entry, heads, reserve):
    """1.3.3 forecast rules adapted to explicit 2.0 bindings, without old Store.

    Material i -> Ti remains a labelled assumption, never an accounting mapping.
    Sum all heads of the same spool before applying the reserve once.
    """
    match=re.search(r'\.(\d+)\.gcode$',entry['source'])
    result=dict(entry,plate=int(match[1])+1 if match else None,mapping_assumed=True)
    if entry['state']!='ready':return dict(result,rows=[],status='unknown')
    totals={}
    for head,used in zip(heads,entry['weights']):
        spool=head['spool']
        if spool:totals[spool['spool_id']]=totals.get(spool['spool_id'],0)+used
    rows=[]
    for head,used in zip(heads,entry['weights']):
        spool=head['spool'];remaining=spool['remaining_mg']/1000 if spool else None
        required=totals.get(spool['spool_id'],used) if spool else used
        unknown=bool(used and not head.get('forecast_usable',head['usable']))
        provisional=bool(used and not unknown and not head['usable'])
        enough=bool(not used or not unknown and remaining is not None and remaining>=required+reserve)
        rows.append(dict(head,used=used,remaining=remaining,
                         after=remaining-required if remaining is not None else None,
                         deficit=max(0,required+reserve-remaining) if remaining is not None else None,
                         unknown=unknown,enough=enough,provisional=provisional,
                         status='unused' if not used else 'unknown' if unknown else 'ok' if enough else 'shortage'))
    status=('unknown' if not any(entry['weights']) or any(r['unknown'] for r in rows)
            else 'shortage' if any(not r['enough'] for r in rows) else 'ok')
    return dict(result,rows=rows,status=status,provisional=any(r['provisional'] for r in rows))


def enrich(snapshot, inventory):
    """Shared overview/tray view model. Selected plate stays a GUI-only choice."""
    entries=snapshot['entries'];latest=next((e for e in entries if e['source']==snapshot['latest']),None)
    project=str(Path(latest['source']).parent.parent) if latest else None
    current=[e for e in entries if (project is None or str(Path(e['source']).parent.parent)==project)
             and not (e.get('sha256') in inventory['accounted'] and
                      e.get('completed_at_ns',0)/1e9<=inventory['accounted'][e['sha256']])]
    ready=[e for e in current if e['state']=='ready']
    source=max(ready,key=lambda e:e['completed_at_ns'])['source'] if ready else None
    printers={pid:dict(p,entries=[forecast_entry(e,p['heads'],inventory['safety_margin_g']) for e in current])
              for pid,p in inventory['printers'].items()}
    selected=inventory['selected_printer']
    if selected not in printers:selected=next(iter(printers),'')
    return dict(snapshot,entries=current,latest=source,project=project,printers=printers,
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
            if self.observer is None:self.observer=SliceObserver(root)
            self.observer.poll()
            entries=copy.deepcopy(list(self.observer.entries.values()))
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
