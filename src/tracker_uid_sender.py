"""Bounded HTTP worker; no database connection and no printer controls.

Explicit server allowlist. No sender starts during application import or owner
construction. Stop/join the worker before closing its AccountingOwner.
"""
import threading
from tracker_uid_spoolman import Client, catalog_item, endpoint


class Sender:
    def __init__(self, owner, allowed_urls, *, client_factory=Client, interval=3):
        self.owner=owner
        self.allowed_urls=frozenset(endpoint(url) for url in allowed_urls)
        if not self.allowed_urls or interval<=0:raise ValueError('Explicit server allowlist and positive interval required')
        self.client_factory=client_factory;self.interval=interval
        self._stop=threading.Event();self._mutex=threading.Lock();self._thread=None
        self.last_error=None

    def send_one(self):
        with self._mutex:
            rows=self.owner.call('delivery_list')
            if any(r['state'] in ('sending','uncertain') for r in rows):return 'blocked'
            row=next((r for r in rows if r['state']=='pending' and r['url'] in self.allowed_urls),None)
            if row is None:return 'idle'
            # Reads are safe to retry. No SQL transaction is held during network I/O.
            try:
                client=self.client_factory(row['url'])
                info,_=client.request('GET','/info')
                if info.get('version')!='0.27.1':return 'unavailable'
                raw,_=client.request('GET',f"/spool/{row['remote_id']}")
                item=catalog_item(raw)
                if (item['id']!=row['remote_id'] or item['archived'] or item['remaining_g'] is None
                        or item['remaining_g']<row['delta_mg']/1000):return 'unavailable'
            except Exception:return 'unavailable'
            if self._stop.is_set():return 'stopped'
            claim=self.owner.call('delivery_claim',row['operation_id'],row['revision'])
            if claim is None:return 'blocked'
            sent=False
            try:
                raw,_=client.request('PUT',f"/spool/{row['remote_id']}/use",{'use_weight':row['delta_mg']/1000})
                item=catalog_item(raw)
                sent=item['id']==row['remote_id'] and item['remaining_g'] is not None
            except Exception:
                pass # Even HTTP 4xx/5xx cannot prove that a write did not occur.
            # A failed DB acknowledgement leaves durable 'sending', never pending.
            result=self.owner.call('delivery_finish',claim['operation_id'],claim['attempt'],sent)
            return result['state']

    def start(self):
        if self._thread is not None:raise RuntimeError('Sender already started')
        def run():
            while not self._stop.is_set():
                try:self.send_one()
                except Exception:
                    self.last_error='Sender stopped after owner failure'
                    self._stop.set()
                    return
                self._stop.wait(self.interval)
        self._thread=threading.Thread(target=run,name='uid-spoolman-http')
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:self._thread.join()
