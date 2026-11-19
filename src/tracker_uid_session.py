"""Isolated app session: lifecycle gate around producers, settings and restore.

Caller supplies data directory and optional collector factory. Never discovers
installed configuration. Restores never auto-connect or enable remote delivery.
"""
import copy
import json
from pathlib import Path
import threading
import uuid
from tracker_uid_client import PrinterEndpoint, UidFleet
from tracker_uid_runtime import AccountingOwner
from tracker_uid_settings import validate_printers
from tracker_uid_migration import atomic


class ManagedFleet:
    def __init__(self):
        self.lock=threading.Lock();self.fleet=None;self.printers=[]
    def snapshot(self):
        with self.lock: fleet=self.fleet;printers=copy.deepcopy(self.printers)
        if fleet:return fleet.snapshot()
        return {p['id']:dict(printer_id=p['id'],name=p['name'],state='stopped',channels={str(i):dict(state='unknown',uid=None) for i in range(4)}) for p in printers}


class Session:
    def __init__(self, directory, *, fleet_factory=UidFleet, worker_factory=None, allowed_urls=None):
        self.directory=Path(directory).resolve();self.directory.mkdir(parents=True,exist_ok=True)
        self.fleet=ManagedFleet();self.lock=threading.RLock();self.workers=[];self.connected=False;self.closed=False
        self.fleet_factory=fleet_factory;self.worker_factory=worker_factory
        self.allowed_urls=None if allowed_urls is None else set(allowed_urls)
        self.owner=AccountingOwner(self.directory/'tracker.sqlite',self.fleet)
        self._load()
    def _load(self):
        printers=self.owner.call('settings')['values'].get('printers',[])
        with self.fleet.lock:self.fleet.printers=printers
    def _stop(self):
        # Do not close/replace the owner until every producer has acknowledged stop.
        for worker in self.workers:worker.stop()
        self.workers=[]
        with self.fleet.lock:fleet=self.fleet.fleet
        if fleet:fleet.stop()
        with self.fleet.lock:self.fleet.fleet=None
        self.connected=False
        for p in self.fleet.printers:
            self.owner.call('disconnected',p['id'],'Connections stopped')
            self.owner.call('monitor_clear',p['id'])
        self.owner.call('refresh')
    def _connect(self):
        if self.connected:return {'connected':True}
        printers=validate_printers(self.fleet.printers)
        if not printers:raise ValueError('Добавьте принтер.')
        if self.allowed_urls is not None and any(p['url'] not in self.allowed_urls for p in printers):
            raise ValueError('Этот адрес не разрешён на изолированном стенде.')
        fleet=self.fleet_factory([PrinterEndpoint(p['id'],p['name'],p['url']) for p in printers])
        with self.fleet.lock:self.fleet.fleet=fleet
        try:
            fleet.start();self.connected=True
            values=self.owner.call('settings')['values']
            if values.get('spoolman_url') and values.get('spoolman_mode','off')!='off':
                from tracker_rfid import RfidWorker
                urls=[values['spoolman_url']] if values.get('spoolman_url') else []
                if self.allowed_urls is not None:
                    urls=[u for u in urls if u in self.allowed_urls]
                worker=RfidWorker(self.owner,urls,interactive=True)
                self.workers.append(worker);worker.start()
            if self.worker_factory:
                for p in printers:
                    worker=self.worker_factory(self.owner,p,self.directory)
                    self.workers.append(worker);worker.start()
        except BaseException:
            self._stop();raise
        return {'connected':True}
    def call(self, operation, *args, **kwargs):
        with self.lock:
            if operation=='guard_action':
                if not self.connected:raise ValueError('Подключения остановлены.')
                from tracker_uid_collectors import ReadOnlyMoonraker
                from tracker_uid_guard import execute
                pid=kwargs.pop('printer_id');p=next(p for p in self.fleet.printers if p['id']==pid)
                if self.allowed_urls is not None and p['url'] not in self.allowed_urls:raise ValueError('Адрес не разрешён.')
                ticket=self.owner.call('guard_decision',pid,**kwargs)
                return execute(self.owner,pid,ReadOnlyMoonraker(p['url']),ticket)
            if operation=='head_counters':
                if not self.connected:raise ValueError('Подключения остановлены.')
                from tracker_uid_collectors import ReadOnlyMoonraker
                from moonraker import MoonrakerClient,MoonrakerError
                from types import SimpleNamespace
                values=self.owner.call('settings')['values'];printers=values.get('printers',[])
                pid=values.get('selected_printer') or (printers[0]['id'] if printers else '')
                p=next(p for p in printers if p['id']==pid)
                if self.allowed_urls is not None and p['url'] not in self.allowed_urls:raise ValueError('Адрес не разрешён.')
                # Reuse the published counter parser with the restricted read-only
                # transport. Do not instantiate legacy monitor or action clients.
                try:heads=MoonrakerClient.head_maintenance(SimpleNamespace(_json=ReadOnlyMoonraker(p['url']).read))
                except MoonrakerError as exc:raise ValueError(str(exc)) from exc
                return dict(heads=heads)
            if operation=='test_printer':
                from tracker_uid_collectors import ReadOnlyMoonraker
                p=validate_printers([dict(id='probe',name='Probe',url=kwargs['url'])])[0]
                if self.allowed_urls is not None and p['url'] not in self.allowed_urls:
                    raise ValueError('Этот адрес не разрешён на изолированном стенде.')
                client=ReadOnlyMoonraker(p['url'])
                status=client.status()
                objects=client.read('/printer/objects/list').get('objects',[])
                return dict(state=status['print_stats']['state'],uid_available='tracker_uid' in objects)
            if operation=='desktop_snapshot':
                result=self.owner.call(operation,*args,**kwargs)
                result['printer']['enabled']=self.connected
                if not self.connected:
                    result['monitor'].update(connected=False,state='disabled',filename='',active_head=None,checked_at=0)
                elif not result['monitor']['connected']:
                    result['monitor']['state']='disconnected'
                return result
            if operation=='connection_state':return {'connected':self.connected,'collectors_enabled':self.worker_factory is not None}
            if operation in ('connect_printers','disconnect_printers'):
                if kwargs.get('confirmed') is not True or set(kwargs)-{'confirmed','expected_revision'}:raise ValueError('Подтвердите изменение подключений.')
                if 'expected_revision' in kwargs and kwargs['expected_revision']!=self.owner.call('settings')['revision']:
                    raise ValueError('Настройки изменились. Проверьте список принтеров заново.')
                if operation=='connect_printers':return self._connect()
                self._stop();return {'connected':False}
            if operation=='save_settings' and {'guard_modes','rfid','spoolman_url','spoolman_mode'} & set(kwargs.get('values',{})) and self.connected:
                raise ValueError('Сначала остановите подключения для изменения режима проверки старта.')
            if operation=='save_settings' and 'printers' in kwargs.get('values',{}):
                if self.connected:raise ValueError('Сначала остановите подключения.')
                old=self.owner.call('settings')['values'].get('printers',[])
                new=validate_printers(kwargs['values']['printers'])
                # Retain historical identities: removal would hide unresolved jobs/assignments.
                if {p['id'] for p in old}-{p['id'] for p in new}:
                    raise ValueError('Удаление постоянных ID недоступно. Остановите подключения.')
                result=self.owner.call(operation,*args,**kwargs);self._load();return result
            if operation in ('validate_backup','restore_backup'):
                if self.connected:raise ValueError('Сначала остановите подключения для восстановления.')
                if operation=='restore_backup':
                    if any(r['state']=='sending' for r in self.owner.call('delivery_list')):
                        raise ValueError('Отправка Spoolman ещё выполняется. Дождитесь результата.')
                    if kwargs.pop('confirmed',False) is not True:raise ValueError('Подтвердите замену базы.')
                    # Validate before writing rollback file or touching current state.
                    preview=self.owner.call('validate_backup',package=kwargs['package'])
                    if preview['current_revision']!=kwargs['expected_revision']:raise ValueError('База изменилась. Проверьте копию снова.')
                    rollback=self.owner.call('backup_package')
                    name='before-restore-'+uuid.uuid4().hex+'.json'
                    atomic(self.directory/name,json.dumps(rollback).encode())
                    result=self.owner.call(operation,**kwargs);self._load()
                    return dict(result,rollback_file=name,connected=False)
            return self.owner.call(operation,*args,**kwargs)
    def close(self):
        with self.lock:
            if self.closed:return
            self._stop();self.owner.close();self.closed=True
