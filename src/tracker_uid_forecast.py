"""Read-only pre-upload forecasts. Never supplies plans to accounting."""
import copy
import logging
from pathlib import Path
import threading
import time
from slice_observer import SliceObserver


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
