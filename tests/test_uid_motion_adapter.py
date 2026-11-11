"""Offline replay through the corrected collector and the UID service."""
import copy
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tracker_uid_accounting import TrackerUidService
from tracker_uid_catalog import UidCatalog
from tracker_uid_motion_adapter import UidMotionAdapter
from test_uid_accounting import snapshot
from test_stream_accounting import make_evidence
from test_accounting import setup_plan


@pytest.fixture
def bench(tmp_path):
    store, *_ = setup_plan(tmp_path)
    catalog = UidCatalog(tmp_path / 'uid.sqlite')
    catalog.register('04112233', 'A', 500000)
    catalog.register('04AABBCC', 'B', 300000)
    class Fleet:
        states = {'a': snapshot('a', {'0': '04112233'}), 'b': snapshot('b', {'1': '04AABBCC'})}
        def snapshot(self): return copy.deepcopy(self.states)
    fleet = Fleet()
    service = TrackerUidService(fleet, catalog)
    adapter = UidMotionAdapter(service)
    yield store, catalog, fleet, adapter
    catalog.close()


def history(state='in_progress', ident='same', start=1010.0):
    return dict(job_id=ident, start_time=start, filename='job.gcode', status=state)


def evidence(store, head=0, length=100):
    result = make_evidence(store)
    result['heads'] = [{'head': i, 'net_mm': length if i == head else 0} for i in range(4)]
    result['comparison']['printer_total_mm'] = length
    return result


def begin(adapter, pid, ev, h=None):
    return adapter.observe_start(pid, h or history(), observed=True, capture_id=ev['capture_id'],
                                 epoch=ev['epoch'], start=ev['start'],
                                 channels=[str(x['head']) for x in ev['heads'] if x['net_mm'] > 0])


def test_parallel_cancel_transfer_replay_and_reopen(bench, tmp_path):
    store, c, f, a = bench
    e = evidence(store); other = evidence(store, 1, 200)
    assert begin(a, 'a', e)['status'] == 'started'
    assert begin(a, 'b', other)['status'] == 'started'
    assert a.finish('a', history('cancelled'), e)['totals_mg'] == {'0': 298}
    assert a.finish('b', history('completed'), other)['totals_mg'] == {'1': 597}
    f.states = {'a': snapshot('a', {}), 'b': snapshot('b', {'2': '04112233', '1': '04AABBCC'})}
    moved = evidence(store, 2, 100)
    h = history(ident='next')
    assert begin(a, 'b', moved, h)['status'] == 'started'
    assert a.finish('b', dict(h, status='completed'), moved)['status'] == 'applied'
    c.close()
    c2 = UidCatalog(tmp_path / 'uid.sqlite')
    try:
        a2 = UidMotionAdapter(TrackerUidService(f, c2))
        assert a2.finish('a', history('cancelled'), e)['status'] == 'duplicate'
        assert c2.spool('04112233')['remaining_mg'] == 499404
        assert c2.spool('04AABBCC')['remaining_mg'] == 299403
    finally:
        c2.close()


@pytest.mark.parametrize('fault', ['missing_start', 'gap', 'uid_restart', 'capture', 'total', 'profile', 'incomplete', 'head', 'insertion'])
def test_uncertainty_persisted_without_debit(bench, fault):
    store, c, f, a = bench
    e = evidence(store)
    if fault != 'missing_start': assert begin(a, 'a', e)['status'] == 'started'
    if fault == 'gap': a.observation_gap('a', 'Motion disconnected')
    if fault == 'uid_restart': f.states['a']['client_session'] = 'new-session'
    if fault == 'capture': e['capture_id'] = 'new'
    if fault == 'total': e['comparison']['printer_total_mm'] = 500
    if fault == 'profile': e['profile']['started_at'] += 1
    if fault == 'incomplete': e['complete'] = False
    if fault == 'head': e['heads'][1]['net_mm'] = 10; e['comparison']['printer_total_mm'] = 110
    if fault == 'insertion': e['feed']['insertions'][0] = True
    assert a.finish('a', history('cancelled'), e)['status'] == 'review'
    assert c.spool('04112233')['remaining_mg'] == 500000
    assert c.db.execute('SELECT reason FROM uid_motion_review').fetchone()[0]


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('prior_state', ['printing', 'paused', 'error'])
def test_corrected_collector_cancel_after_error_uses_frozen_boundary(bench, monkeypatch, prior_state, automatic):
    """Run the actual fixed recorder on a fake socket; intercept its debit sink.

    No network/thread started. Legacy commit functions are replaced ONLY in this
    simulator, so the old database is never debited alongside the new one.
    """
    import importlib.util
    import accounting
    import time
    from types import SimpleNamespace
    store, c, f, a = bench
    path = ROOT / 'dev/labs/uid_motion_bench/recorder_fixture.py'
    spec = importlib.util.spec_from_file_location('fixed_motion_source', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture_db = store.read()
    fixture_db['runs']['sim'] = dict(filename='job.gcode', start_time=1010.0, status='cancelled', terminal_status='cancelled')
    monkeypatch.setattr(store, 'read', lambda: copy.deepcopy(fixture_db))
    e = evidence(store)
    e['capture_id'] = e['epoch'] = 'sim-capture'
    if automatic:
        from tracker_uid_motion_lifecycle import MotionLifecycle
        lifecycle = MotionLifecycle(a)
    else:
        lifecycle = None
        assert begin(a, 'a', e)['status'] == 'started'
    profile = e['profile']
    before = copy.deepcopy(store.read()['spools'])
    monkeypatch.setattr(module.uuid, 'uuid4', lambda: SimpleNamespace(hex='sim-capture'))
    tick = iter(range(1000))
    monkeypatch.setattr(time, 'monotonic', lambda: next(tick))
    monkeypatch.setattr(time, 'time', lambda: 1010.0)
    def no_slicer(*args): raise ValueError('Bench requires motion only')
    monkeypatch.setattr(accounting, 'commit_unchanged_slicer_estimate', no_slicer)
    results = []
    def sink(store_arg, key, captured):
        results.append(a.finish('a', history('cancelled'), captured))
        return results[-1]['status'] == 'applied'
    monkeypatch.setattr(accounting, 'commit_stream_estimate', sink)
    channel = dict(module_exist=True, disable_auto=False, filament_detected=True)
    initial = {'print_stats': {'state': 'standby'},
               'filament_detect': {'state': [0]*4, 'info': [{'CARD_UID': 0} for _ in range(4)]},
               'filament_feed left': {'extruder0': channel, 'extruder1': channel},
               'filament_feed right': {'extruder2': channel, 'extruder3': channel}}
    def status(**stats): return {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': stats}}}
    def motion(rows): return {'method': 'notify_tracker_head_0', 'params': {'data': rows}}
    def move(t, n): return [t, 1, n, 0, [0,0,0], [1,0,0]]
    recorder = module.MotionStreamRecorder(store, lifecycle=lifecycle, printer_id='a', channels=['0'])
    class Socket:
        items = [{'id': 10, 'result': {'status': initial}},
                 *[{'id': i, 'result': {}} for i in range(1,5)],
                 status(state='printing', filename='job.gcode', filament_used=0),
                 motion([move(1, 100)]), status(state=prior_state, filament_used=100),
                 status(state='cancelled', filament_used=100.12),
                 motion([move(2, .12), move(3, -2)]), status(filament_used=100.12)]
        empty = 0
        def send(self, payload): pass
        def receive(self):
            if self.items:
                item = self.items.pop(0)
                if item.get('method') == 'notify_tracker_head_0':
                    store._motion_slicer_profile = profile
                    if automatic: lifecycle.history('a', [history('cancelled')])
                return item
            self.empty += 1
            if results or self.empty > 40: recorder.stop_event.set()
            return None
    try:
        recorder._capture(Socket(), store.read()['printer'])
    finally:
        recorder.stop()
    if automatic:
        assert results == []  # Old debit sink was never called.
        assert lifecycle.history('a', [history('cancelled')]) == [{'status': 'duplicate', 'totals_mg': {'0': 299}}]
    else:
        assert results == [{'status': 'applied', 'totals_mg': {'0': 299}}]
    assert c.spool('04112233')['remaining_mg'] == 499701
    assert store.read()['spools'] == before
