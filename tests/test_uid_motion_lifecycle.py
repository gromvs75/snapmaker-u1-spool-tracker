import copy
import pytest
from test_uid_motion_adapter import bench, evidence, history
from test_uid_accounting import snapshot
from tracker_uid_motion_lifecycle import MotionLifecycle
from tracker_uid_motion_adapter import UidMotionAdapter
from tracker_uid_accounting import TrackerUidService
from tracker_uid_catalog import UidCatalog


def start(life, pid, e, observed=1011):
    return life.start(pid, filename='job.gcode', observed_at=observed,
                      capture_id=e['capture_id'], epoch=e['epoch'], start=e['start'],
                      channels=[str(x['head']) for x in e['heads'] if x['net_mm'] > 0])


def terminal(store, head=0):
    e = evidence(store, head)
    e['terminal_state'] = 'cancelled'
    return e


@pytest.mark.parametrize('history_first', [True, False])
def test_automatic_late_history_and_durable_duplicate(bench, tmp_path, history_first):
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter)
    e = terminal(store)
    assert start(life, 'a', e)['status'] == 'started'
    if history_first: assert life.history('a', [history('cancelled')]) == [{'status': 'pending'}]
    result = life.terminal('a', e)
    if not history_first: result = life.history('a', [history('cancelled')])[0]
    assert result['status'] == 'applied'
    assert life.history('a', [history('cancelled')])[0]['status'] == 'duplicate'
    c.close()
    reopened = UidCatalog(tmp_path / 'uid.sqlite')
    try:
        resumed = MotionLifecycle(UidMotionAdapter(TrackerUidService(fleet, reopened)))
        assert resumed.history('a', [history('cancelled')])[0]['status'] == 'duplicate'
        assert reopened.spool('04112233')['remaining_mg'] == 499702
        assert reopened.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 1
    finally: reopened.close()


@pytest.mark.parametrize('fault', ['disconnect', 'restart', 'uid_change', 'ambiguous', 'wrong_time', 'wrong_file', 'terminal_mismatch'])
def test_failed_join_or_gap_never_debits(bench, fault):
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter); e = terminal(store)
    start(life, 'a', e)
    if fault == 'disconnect': life.disconnected('a'); life.disconnected('a')
    if fault == 'restart': life = MotionLifecycle(adapter)
    if fault == 'uid_change': fleet.states['a']['generation'] = 2
    life.terminal('a', e)
    jobs = [history('cancelled')]
    if fault == 'ambiguous': jobs.append(history('cancelled', ident='other', start=1012))
    if fault == 'wrong_time': jobs[0]['start_time'] = 1100
    if fault == 'wrong_file': jobs[0]['filename'] = 'other.gcode'
    if fault == 'terminal_mismatch': jobs[0]['status'] = 'completed'
    life.history('a', jobs)
    assert c.spool('04112233')['remaining_mg'] == 500000


def test_two_printers_gap_does_not_block_other(bench):
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter)
    ea, eb = terminal(store), terminal(store, 1)
    start(life, 'a', ea); start(life, 'b', eb)
    life.disconnected('a')
    life.terminal('a', ea); life.terminal('b', eb)
    assert life.history('a', [history('cancelled')])[0]['status'] == 'review'
    assert life.history('b', [history('cancelled')])[0]['status'] == 'applied'
    assert c.spool('04112233')['remaining_mg'] == 500000
    assert c.spool('04AABBCC')['remaining_mg'] == 299702


def test_transfer_then_old_history_uses_saved_binding(bench):
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter); e = terminal(store)
    start(life, 'a', e); life.terminal('a', e)
    life.history('a', [history('cancelled')])
    fleet.states = {'a': snapshot('a', {}), 'b': snapshot('b', {'2': '04112233'})}
    moved = terminal(store, 2); moved['capture_id'] = 'second'
    moved['profile']['started_at'] = 1100.0
    start(life, 'b', moved, observed=1101)
    life.terminal('b', moved)
    assert life.history('b', [history('cancelled', ident='second', start=1100.0)])[0]['status'] == 'applied'
    assert life.history('a', [history('cancelled')])[0]['status'] == 'duplicate'
    assert c.spool('04112233')['remaining_mg'] == 499404


def test_ambiguity_stays_blocked_when_history_page_changes(bench):
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter); e = terminal(store)
    start(life, 'a', e); life.terminal('a', e)
    life.history('a', [history('cancelled'), history('cancelled', ident='other', start=1012)])
    assert life.history('a', [history('cancelled')])[0]['status'] == 'review'
    assert c.spool('04112233')['remaining_mg'] == 500000


def test_collector_socket_exception_marks_job_invalid_and_reconnect_does_not_start(bench, monkeypatch):
    import importlib.util
    from pathlib import Path
    import time
    store, c, fleet, adapter = bench
    life = MotionLifecycle(adapter)
    path = Path(__file__).resolve().parents[1] / 'dev/labs/uid_motion_bench/recorder_fixture.py'
    spec = importlib.util.spec_from_file_location('lifecycle_recorder', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(time, 'time', lambda: 1010.0)
    recorder = module.MotionStreamRecorder(store, lifecycle=life, printer_id='a', channels=['0'])
    class Socket:
        def __init__(self, initial):
            self.messages = [{'id': 10, 'result': {'status': {'print_stats': {'state': initial, 'filename': 'job.gcode'}}}},
                             *[{'id': i, 'result': {}} for i in range(1,5)],
                             {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'job.gcode'}}}}]
        def send(self, payload): pass
        def receive(self):
            if self.messages: return self.messages.pop(0)
            raise module.StreamError('simulated EOF')
    try:
        with pytest.raises(module.StreamError): recorder._capture(Socket('standby'), store.read()['printer'])
        assert c.db.execute('SELECT mapping_valid FROM uid_jobs').fetchone()[0] == 0
        with pytest.raises(module.StreamError): recorder._capture(Socket('printing'), store.read()['printer'])
        assert c.db.execute('SELECT count(*) FROM uid_jobs').fetchone()[0] == 1
        # Reconnect reports the same gap; retain one diagnostic, not one per retry.
        assert c.db.execute('SELECT count(*) FROM uid_motion_review').fetchone()[0] == 1
        assert c.spool('04112233')['remaining_mg'] == 500000
    finally: recorder.stop()


def test_repeated_gap_and_review_are_deduplicated(bench):
    store,c,fleet,adapter=bench
    life=MotionLifecycle(adapter);e=terminal(store)
    key=start(life,'a',e)['job_key']
    for _ in range(50):
        life.disconnected('a','socket unavailable')
        adapter._review(key,'socket unavailable')
    rows=c.db.execute('SELECT reason FROM uid_motion_review WHERE job_key=?',(key,)).fetchall()
    assert [r[0] for r in rows]==['socket unavailable']
    life.disconnected('a','different evidence')
    assert c.db.execute('SELECT count(*) FROM uid_motion_review WHERE job_key=?',(key,)).fetchone()[0]==2
    assert c.db.execute('SELECT mapping_valid FROM uid_jobs WHERE job_key=?',(key,)).fetchone()[0]==0
    assert c.spool('04112233')['remaining_mg']==500000


def test_manual_resolution_fences_late_terminal_and_history(bench):
    import time
    store,c,fleet,adapter=bench
    life=MotionLifecycle(adapter);e=terminal(store)
    key=start(life,'a',e)['job_key'];life.disconnected('a')
    accounting=adapter.service.accounting
    obs={'state':'cancelled','checked_at':time.monotonic(),'connection_token':c.connection_token(fleet.snapshot()['a'])}
    accounting.resolve_interrupted(key,accounting.resolution_version(accounting.job(key)),obs,fleet.snapshot(),confirmed=True,accept_unaccounted=True)
    life.terminal('a',e)
    for _ in range(5):
        assert life.history('a',[history('cancelled')])[0]['status']=='resolved_without_debit'
    assert c.spool('04112233')['remaining_mg']==500000
    assert accounting.job(key)['state']=='resolved'
    assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0
