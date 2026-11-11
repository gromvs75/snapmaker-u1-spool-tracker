"""Threaded offline integration: real collector, fake read-only transports."""
import copy
import importlib.util
from pathlib import Path
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_accounting import setup_plan
from test_stream_accounting import make_evidence
from test_uid_accounting import snapshot
from tracker_uid_runtime import AccountingOwner, PrinterWorkers, ModelInventoryStore


class Fleet:
    def __init__(self):
        self.value = {'a': snapshot('a', {'0': '04112233'}), 'b': snapshot('b', {'1': '04AABBCC'})}
    def snapshot(self): return copy.deepcopy(self.value)


def balances(report): return {s['uid']: s['remaining_mg'] for s in report['spools']}


@pytest.mark.parametrize('manual_spool', [False, True])
@pytest.mark.parametrize('gap_after_start', [False, True])
def test_real_collectors_history_queue_reconnect_and_replay(tmp_path, monkeypatch, gap_after_start, manual_spool):
    import accounting
    def forbidden(*args, **kwargs): raise AssertionError('Legacy accounting was called')
    monkeypatch.setattr(accounting, 'commit_stream_estimate', forbidden)
    monkeypatch.setattr(accounting, 'commit_unchanged_slicer_estimate', forbidden)
    spec = importlib.util.spec_from_file_location('queued_recorder', Path(__file__).resolve().parents[1] / 'dev/labs/uid_motion_bench/recorder_fixture.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    fleet = Fleet()
    path = tmp_path / 'uid.sqlite'
    owner = AccountingOwner(path, fleet, capacity=8)
    if manual_spool:
        fleet.value['a']=snapshot('a',{})
        owner.call('register_manual','Manual',500000,spool_id='manual-id',details={'material':'PLA'})
        owner.call('assign_manual','a','0','manual-id',confirmed=True)
    else:
        owner.call('register', '04112233', 'A', 500000)
    owner.call('register', '04AABBCC', 'B', 300000)
    workers, histories, producer_threads, stores = [], {}, set(), []
    connections = {'a': 0, 'b': 0}
    start_time = time.time()
    try:
        for pid, head in [('a', 0), ('b', 1)]:
            directory = tmp_path / pid; directory.mkdir()
            store, *_ = setup_plan(directory)
            stores.append((store, copy.deepcopy(store.read()['spools'])))
            if manual_spool and pid=='a':
                store=ModelInventoryStore(owner,pid,directory/'model-logs',store.read()['printer'])
            profile = make_evidence(store)['profile']; profile['started_at'] = start_time
            histories[pid] = dict(job_id='same-history-id', start_time=start_time, filename='job.gcode', status='cancelled')
            def factory(proxy, printer_id, store=store, head=head):
                producer_threads.add(threading.get_ident())
                return module.MotionStreamRecorder(store, lifecycle=proxy, printer_id=printer_id, channels=[str(head)])
            channel = dict(module_exist=True, disable_auto=False, filament_detected=True)
            initial = {'print_stats': {'state': 'standby'},
                       'filament_detect': {'state': [0]*4, 'info': [{'CARD_UID': 0} for _ in range(4)]},
                       'filament_feed left': {'extruder0': channel, 'extruder1': channel},
                       'filament_feed right': {'extruder2': channel, 'extruder3': channel}}
            class Socket:
                def __init__(self, initial, store, profile, head, fail):
                    self.closed = threading.Event()
                    self.store, self.profile = store, profile
                    self.messages = [{'id': 10, 'result': {'status': initial}},
                        *[{'id': i, 'result': {}} for i in range(1,5)],
                        {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'job.gcode', 'filament_used': 0}}}},
                        {'method': f'notify_tracker_head_{head}', 'params': {'data': [[1,1,100,0,[0,0,0],[1,0,0]]]}},
                        {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'cancelled', 'filament_used': 100}}}}]
                    self.fail = fail
                def send(self, payload): pass
                def receive(self):
                    if self.closed.is_set(): raise module.StreamError('socket closed')
                    if self.fail and len(self.messages) == 2:
                        raise module.StreamError('injected mid-print EOF')
                    if self.messages:
                        message = self.messages.pop(0)
                        if message.get('method', '').startswith('notify_tracker_head_'):
                            self.store._motion_slicer_profile = self.profile
                        return message
                    self.closed.wait(.02)
                    raise socket.timeout()
                def close(self): self.closed.set()
            def connect(pid=pid, initial=initial, store=store, profile=profile, head=head, Socket=Socket):
                connections[pid] += 1
                n = connections[pid]
                if pid == 'a' and n == 1 and not gap_after_start:
                    raise ConnectionError('injected initial connection failure')
                state = copy.deepcopy(initial)
                if pid == 'a' and gap_after_start and n > 1:
                    state['print_stats'] = {'state': 'printing', 'filename': 'job.gcode'}
                return Socket(state, store, profile, head, pid == 'a' and gap_after_start and n == 1)
            def read_history(pid=pid):
                producer_threads.add(threading.get_ident())
                return [copy.deepcopy(histories[pid])]
            worker = PrinterWorkers(owner, pid, factory, connect, read_history, store.read()['printer'],
                                    poll_interval=.02, reconnect_interval=.02)
            workers.append(worker)
        for worker in workers: worker.start()
        deadline = time.monotonic() + 12
        expected = 1 if gap_after_start else 2
        while time.monotonic() < deadline:
            report = owner.call('inspect')
            if len(report['debits']) == expected: break
            time.sleep(.02)
        assert len(report['debits']) == expected
        assert connections['a'] >= 2
        assert report['thread_id'] not in producer_threads
        assert len(producer_threads) == 4
        assert balances(report) == {None if manual_spool else '04112233': 500000 if gap_after_start else 499702, '04AABBCC': 299702}
        # Concurrent duplicate deliveries from independent producer threads.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda pid: owner.call('history', pid, [histories[pid]]), ['a', 'b'] * 10))
        assert len(owner.call('inspect')['debits']) == expected
        for store, original in stores: assert store.read()['spools'] == original
    finally:
        for worker in workers: worker.stop()
        owner.close()
    assert all(not thread.is_alive() for worker in workers for thread in worker.threads)
    assert not owner.thread.is_alive()
    # Reopening occurs in a new SQLite owner, still with default thread checking.
    reopened = AccountingOwner(path, fleet)
    try:
        for pid in histories: reopened.call('history', pid, [histories[pid]])
        assert len(reopened.call('inspect')['debits']) == expected
        assert balances(reopened.call('inspect')) == balances(report)
    finally: reopened.close()


def test_owner_rejects_after_close_and_survives_bad_command(tmp_path):
    owner = AccountingOwner(tmp_path / 'db', Fleet(), capacity=1)
    try:
        with pytest.raises(ValueError): owner.call('invalid')
        assert owner.call('inspect')['debits'] == []
        futures = [owner.submit('register', '04112233', 'A', 500000) for _ in range(8)]
        owner.close()  # Drains accepted work before closing SQLite.
        assert all(f.result()['remaining_mg'] == 500000 for f in futures)
        with pytest.raises(RuntimeError): owner.submit('inspect')
    finally: owner.close()


def test_queued_payload_and_uid_snapshot_are_copied_at_ingress(tmp_path, monkeypatch):
    from tracker_uid_motion_lifecycle import MotionLifecycle
    store, *_ = setup_plan(tmp_path)
    fleet = Fleet()
    owner = AccountingOwner(tmp_path / 'db', fleet)
    owner.call('register', '04112233', 'A', 500000)
    entered, release = threading.Event(), threading.Event()
    original = MotionLifecycle.history
    def blocked(self, pid, jobs):
        entered.set()
        assert release.wait(5)
        return original(self, pid, jobs)
    monkeypatch.setattr(MotionLifecycle, 'history', blocked)
    try:
        barrier = owner.submit('history', 'a', [])
        assert entered.wait(5)
        start_snapshot = store.read()
        pending = owner.submit('start', 'a', filename='job.gcode', observed_at=1010,
                               capture_id='copied', epoch='epoch', start=start_snapshot, channels=['0'])
        # Both producer-owned structures mutate while the owner is busy.
        start_snapshot['slots'].clear()
        fleet.value['a']['channels']['0']['uid'] = '04DEADBE'
        release.set(); barrier.result()
        assert pending.result()['status'] == 'started'
        # The next UID snapshot invalidates, rather than rebinds, this job.
        owner.call('refresh')
        report = owner.call('inspect')
        assert report['jobs'][0]['mapping_valid'] == 0
        assert report['debits'] == []
    finally:
        release.set(); owner.close()


def test_history_worker_retries_and_records_observation_gap(tmp_path):
    store, *_ = setup_plan(tmp_path)
    owner = AccountingOwner(tmp_path / 'db', Fleet())
    owner.call('register', '04112233', 'A', 500000)
    started, retried = threading.Event(), threading.Event()
    polls = []
    class Recorder:
        def __init__(self, proxy, pid):
            self.proxy, self.pid = proxy, pid
            self.stop_event = threading.Event()
        def _capture(self, sock, config):
            self.proxy.start(self.pid, filename='job.gcode', observed_at=1010,
                             capture_id='history-gap', epoch='epoch', start=store.read(), channels=['0'])
            started.set()
            self.stop_event.wait(5)
        def stop(self): self.stop_event.set()
    class Socket:
        def close(self): pass
    def history_reader():
        assert started.wait(5)
        polls.append(1)
        if len(polls) == 1: raise ConnectionError('History HTTP disconnected')
        retried.set()
        return []
    worker = PrinterWorkers(owner, 'a', Recorder, Socket, history_reader, store.read()['printer'], poll_interval=.01)
    try:
        worker.start()
        assert retried.wait(5)
        report = owner.call('inspect')
        assert report['jobs'][0]['mapping_valid'] == 0
        assert any('History HTTP disconnected' in r['reason'] for r in report['reviews'])
        assert report['debits'] == []
    finally:
        worker.stop(); owner.close()
