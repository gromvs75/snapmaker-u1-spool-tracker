"""Queued multi-printer integration. SQLite belongs exclusively to the owner.

Transports/recorders are injected explicitly; this module discovers no installed
configuration and opens no network connections by itself. Stop producers before
closing the owner. Recorder callbacks wait for acknowledgement (backpressure).
"""
import copy
from concurrent.futures import Future
from queue import Queue, Full
import threading

from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import TrackerUidService
from tracker_uid_motion_adapter import UidMotionAdapter
from tracker_uid_motion_lifecycle import MotionLifecycle


class _SnapshotFleet:
    def __init__(self): self.value = {}
    def snapshot(self): return copy.deepcopy(self.value)


class AccountingOwner:
    def __init__(self, path, fleet, *, capacity=128):
        if capacity < 1: raise ValueError('Positive queue capacity required')
        self.fleet = fleet
        self.queue = Queue(capacity)
        self.lock = threading.Lock()
        self.closed = False
        self.ready = Future()
        self.thread = threading.Thread(target=self._run, args=(path,), name='uid-sqlite-owner')
        self.thread.start()
        self.ready.result()

    def submit(self, operation, *args, **kwargs):
        # Snapshot at ingress, not after arbitrary queue latency. In particular,
        # start must bind the observed UID, not a later replacement in the slot.
        payload = copy.deepcopy((args, kwargs))
        snapshot = copy.deepcopy(self.fleet.snapshot())
        future = Future()
        while True:
            with self.lock:
                if self.closed: raise RuntimeError('Accounting owner closed')
                try:
                    self.queue.put((operation, payload, snapshot, future), timeout=.05)
                    return future
                except Full:
                    pass  # Release admission lock so shutdown/failure can proceed.

    def call(self, operation, *args, **kwargs):
        return self.submit(operation, *args, **kwargs).result()

    def _run(self, path):
        catalog = None
        try:
            catalog = UidCatalog(path)
            fleet = _SnapshotFleet()
            service = TrackerUidService(fleet, catalog)
            lifecycle = MotionLifecycle(UidMotionAdapter(service))
            from tracker_uid_library import Library
            library = Library(service.accounting)
            from tracker_uid_delivery import Delivery
            delivery = Delivery(service.accounting)
            self.ready.set_result(threading.get_ident())
            while True:
                item = self.queue.get()
                if item is None:
                    # Stopping ownership interrupts any still-active capture.
                    for row in catalog.db.execute("SELECT DISTINCT printer_id FROM uid_jobs WHERE state='active'").fetchall():
                        lifecycle.disconnected(row[0], 'SQLite owner stopped')
                    self.queue.task_done()
                    break
                operation, (args, kwargs), snapshot, future = item
                try:
                    fleet.value = snapshot
                    if operation in ('delivery_list','delivery_audit','delivery_decide','delivery_claim','delivery_finish'):
                        result=getattr(delivery,operation.removeprefix('delivery_'))(*args,**kwargs)
                    elif operation in ('settings','save_settings','cache_catalog','remote_catalog','compare_name','rename_from_remote','library_snapshot'):
                        result = getattr(library, 'snapshot' if operation=='library_snapshot' else operation)(*args, **kwargs)
                    elif operation in ('create_spool','detach_spool'):
                        result = getattr(library, 'create' if operation=='create_spool' else 'detach')(*args, fleet=fleet.snapshot(), **kwargs)
                    elif operation == 'register': result = catalog.register(*args, **kwargs)
                    elif operation == 'inventory_snapshot': result = catalog.inventory_snapshot(*args, fleet=fleet.snapshot(), **kwargs)
                    elif operation == 'register_manual': result = catalog.register_manual(*args, **kwargs)
                    elif operation == 'assign_manual': result = service.accounting.assign_manual(*args, fleet=fleet.snapshot(), **kwargs)
                    elif operation == 'transfer_manual': result = service.accounting.transfer_manual(*args, fleet=fleet.snapshot(), **kwargs)
                    elif operation == 'resolve_interrupted': result = service.accounting.resolve_interrupted(*args,fleet=fleet.snapshot(),**kwargs)
                    elif operation == 'release_manual': result = service.accounting.release_manual(*args, **kwargs)
                    elif operation == 'export_backup':
                        import sqlite3, tempfile, base64
                        from pathlib import Path
                        with tempfile.TemporaryDirectory(prefix='uid-backup-') as folder:
                            target=Path(folder)/'tracker.sqlite'
                            backup=sqlite3.connect(target)
                            try: catalog.db.backup(backup)
                            finally: backup.close()
                            result={'filename':'tracker-2.0-backup.sqlite','base64':base64.b64encode(target.read_bytes()).decode()}
                    elif operation == 'active_spools': result = [r[0] for r in catalog.db.execute("SELECT t.spool_id FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE j.state='active'")]
                    elif operation == 'inspect':
                        result = {'thread_id': threading.get_ident(),
                                  'spools': [dict(r) for r in catalog.db.execute('SELECT * FROM uid_spools')],
                                  'manual_assignments': [dict(r) for r in catalog.db.execute('SELECT * FROM manual_assignments')],
                                  'jobs': [dict(r, resolution_version=service.accounting.resolution_version(r),unlock=service.accounting.unlock_state(r['job_key']),spool_ids=[t[0] for t in catalog.db.execute('SELECT spool_id FROM uid_job_tools WHERE job_key=?',(r['job_key'],))]) for r in catalog.db.execute('SELECT j.*,c.filename FROM uid_jobs j LEFT JOIN uid_motion_captures c ON c.key=j.job_key')],
                                  'resolutions': [dict(r) for r in catalog.db.execute('SELECT * FROM uid_manual_resolutions')],
                                  'debits': [dict(r) for r in catalog.db.execute('SELECT * FROM uid_debits')],
                                  'reviews': [dict(r) for r in catalog.db.execute('SELECT * FROM uid_motion_review')]}
                    elif operation == 'refresh': result = service.refresh()
                    elif operation in ('start', 'terminal', 'history', 'disconnected'):
                        result = getattr(lifecycle, operation)(*args, **kwargs)
                    else: raise ValueError('Unknown accounting operation')
                    if not future.cancelled(): future.set_result(result)
                except Exception as exc:
                    if not future.cancelled(): future.set_exception(exc)
                finally:
                    self.queue.task_done()
        except BaseException as exc:
            if not self.ready.done(): self.ready.set_exception(exc)
            # Unexpected owner failure must not leave producers waiting forever.
            with self.lock:
                self.closed = True
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[3].done(): item[3].set_exception(exc)
                self.queue.task_done()
        finally:
            if catalog is not None: catalog.close()

    def close(self):
        with self.lock:
            enqueue_stop = not self.closed
            self.closed = True
        if enqueue_stop:
            while self.thread.is_alive():
                try:
                    self.queue.put(None, timeout=.05)
                    break
                except Full:
                    continue
        self.thread.join()


class QueuedLifecycle:
    """Recorder-facing facade; never exposes a connection or lifecycle object."""
    def __init__(self, owner): self.owner = owner
    def start(self, printer_id, **kwargs): return self.owner.call('start', printer_id, **kwargs)
    def terminal(self, printer_id, evidence): return self.owner.call('terminal', printer_id, evidence)
    def disconnected(self, printer_id, reason='Motion disconnected'):
        return self.owner.call('disconnected', printer_id, reason)


class PrinterWorkers:
    """Independent motion + history workers for one persistent printer ID.

    recorder_factory(proxy, printer_id) must construct a recorder with legacy
    debit disabled. socket_factory returns a bounded-timeout motion socket;
    history_reader is a read-only history() callable with bounded I/O. Neither
    worker invokes the old polling/accounting pipeline.
    """
    def __init__(self, owner, printer_id, recorder_factory, socket_factory, history_reader,
                 config, *, poll_interval=3, reconnect_interval=1):
        self.owner, self.printer_id = owner, printer_id
        self.proxy = QueuedLifecycle(owner)
        self.recorder_factory, self.socket_factory = recorder_factory, socket_factory
        self.history_reader, self.config = history_reader, copy.deepcopy(config)
        self.poll_interval, self.reconnect_interval = poll_interval, reconnect_interval
        self.stop_event = threading.Event()
        self.errors = Queue()
        self.socket_lock = threading.Lock()
        self.socket = None
        self.recorder = None
        self.threads = [threading.Thread(target=self._motion, name=f'motion-{printer_id}'),
                        threading.Thread(target=self._history, name=f'history-{printer_id}')]

    def start(self):
        for thread in self.threads: thread.start()

    def _gap(self, error):
        self.errors.put(str(error))
        self.proxy.disconnected(self.printer_id, str(error))

    def _motion(self):
        try:
            self.recorder = self.recorder_factory(self.proxy, self.printer_id)
            while not self.stop_event.is_set():
                sock = None
                try:
                    sock = self.socket_factory()
                    with self.socket_lock:
                        self.socket = sock
                    if self.stop_event.is_set(): break
                    self.recorder._capture(sock, self.config)
                except Exception as exc:
                    self._gap(exc)
                finally:
                    if sock is not None: sock.close()
                    with self.socket_lock: self.socket = None
                self.stop_event.wait(self.reconnect_interval)
        except Exception as exc:
            self._gap(exc)
        finally:
            if self.recorder is not None: self.recorder.stop()
            self.proxy.disconnected(self.printer_id, 'Motion worker stopped')

    def _history(self):
        while not self.stop_event.is_set():
            try:
                jobs = self.history_reader()
                self.owner.call('history', self.printer_id, jobs)
            except Exception as exc:
                self._gap(exc)
            self.stop_event.wait(self.poll_interval)

    def stop(self, timeout=15):
        self.stop_event.set()
        if self.recorder is not None: self.recorder.stop_event.set()
        with self.socket_lock:
            if self.socket is not None: self.socket.close()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout)
                if thread.is_alive(): raise TimeoutError(f'Worker did not stop: {thread.name}')


class ModelInventoryStore:
    """Read-only collector view of the 2.0 inventory, through the owner queue.

    Only diagnostic log directory and explicit bench connection config are local.
    Material profiles may be attached by the independent history/profile reader.
    """
    def __init__(self, owner, printer_id, directory, config):
        from pathlib import Path
        self.owner, self.printer_id = owner, printer_id
        self.directory = Path(directory)
        self.config = copy.deepcopy(config)

    def read(self):
        result=self.owner.call('inventory_snapshot',self.printer_id)
        result['printer']=copy.deepcopy(self.config)
        return result
