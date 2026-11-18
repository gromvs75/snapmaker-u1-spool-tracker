"""Sanitized Windows report cases; no user data or device connections.

These are controlled scenarios using the saved plans, not a replay of missing
packets. A real motion gap must still require review for an untagged spool.
"""
import copy
import socket
from types import SimpleNamespace

import pytest

from test_uid_accounting import snapshot
from test_uid_motion_adapter import bench, evidence, history
from test_manual_without_uid import stock
from test_uid_collectors import Client
from tracker_uid_collectors import ProfileHistory
from tracker_uid_motion_lifecycle import MotionLifecycle


CASES = [
    ('000180', 1, 3, 1.55), ('000181', 1, 3, 2.85),
    ('000182', 3, 3, 8.49), ('000183', 1, 1, 178.48),
    ('000184', 2, 2, 74.30), ('000185', 1, 1, 13.77),
    ('000186', 3, 3, 55.40), ('000187', 3, 3, 8.34),
]


@pytest.mark.parametrize('job_id,logical,head,grams', CASES)
@pytest.mark.parametrize('fault', ['http_timeout', 'motion_gap', 'prior_motion_gap', 'missing_terminal_map'])
def test_untagged_spool_auto_off_and_terminal_replay(bench, job_id, logical, head, grams, fault):
    store, catalog, fleet, adapter = bench
    fleet.states['a'] = stock(snapshot('a', {}))
    sid = catalog.register_manual('Windows test spool', 1000000)['spool_id']
    accounting = adapter.service.accounting
    from tracker_uid_library import Library
    Library(accounting)
    accounting.assign_manual('a', str(head), sid, fleet.states, confirmed=True)
    # Spoolman identity is independent of RFID identity. No sender is started.
    catalog.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',
                       (sid, 'http://127.0.0.1:19999', 42))
    catalog.db.commit()
    life = MotionLifecycle(adapter)
    job = history(ident=job_id)
    e = evidence(store, head=head)
    e.update(start=catalog.inventory_snapshot('a', fleet.states), terminal_state='completed',
             comparison={'matches': False, 'printer_total_mm': None}, mapping_consistent=True)
    e['feed']['runouts'] = [False]*4
    mapping = list(range(4)); mapping[logical] = head
    weights = [0.0]*4; weights[logical] = grams
    feed = {'filament_feed ' + ('left' if head < 2 else 'right'):
            {'extruder'+str(head): {'filament_detected': True}}}
    e['profile'].update(file_sha256='a'*64, logical_weights=weights, mapping=mapping,
                        replenished=list(range(4)), auto_replenish=False, feed_start=feed)
    life.start('a', filename=job['filename'], observed_at=job['start_time'],
               capture_id=e['capture_id'], epoch=e['epoch'], start=e['start'], channels=[str(head)])
    life.recovery_profile('a', job, e['profile'])
    if fault == 'prior_motion_gap':
        life.disconnected('a', 'WebSocket disconnected before HTTP timeout')
    life.history_timeout('a', 'timed out')
    if fault == 'motion_gap':
        life.disconnected('a', 'WebSocket disconnected')
    life.terminal('a', e)
    status = dict(print_stats=dict(state='complete', filename=job['filename']),
                  print_task_config=dict(auto_replenish_filament=False,
                                         extruder_map_table=mapping+[0]*28,
                                         extruders_replenished=list(range(4))), **feed)
    terminal = dict(job, status='completed')
    if fault == 'missing_terminal_map':
        missing = copy.deepcopy(status)
        missing['print_task_config']['extruder_map_table'] = []
        assert life.recovery_terminal('a', terminal, missing, 'a'*64)['status'] == 'review'
        assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    result = life.recovery_terminal('a', terminal, status, 'a'*64)
    if fault in ('motion_gap', 'prior_motion_gap'):
        assert result['status'] == 'review'
        assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
        assert not catalog.db.execute('SELECT * FROM uid_remote_outbox').fetchall()
        assert catalog.db.execute('SELECT remaining_mg FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()[0] == 1000000
        return
    assert result['status'] == 'applied', result
    assert result['totals_mg'] == {str(head): round(grams*1000)}
    life = MotionLifecycle(adapter)
    for _ in range(5):
        assert life.recovery_terminal('a', terminal, status, 'a'*64)['status'] == 'duplicate'
    assert catalog.db.execute('SELECT remaining_mg FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()[0] == 1000000-round(grams*1000)
    assert catalog.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 1
    remote = catalog.db.execute('SELECT remote_id,delta_mg,state FROM uid_remote_outbox').fetchall()
    assert [tuple(r) for r in remote] == [(42, round(grams*1000), 'held')]


@pytest.mark.parametrize('endpoint', ['history', 'status', 'inspect'])
def test_http_timeout_retains_verified_profile_for_retry(endpoint, monkeypatch):
    monkeypatch.setattr('time.monotonic', lambda: 100.)
    client = Client(); store = SimpleNamespace(); reader = ProfileHistory(client, store)
    reader(); verified = store._motion_slicer_profile
    original = getattr(client, endpoint)
    if endpoint == 'inspect':
        client.state = 'complete'; client.job['status'] = 'completed'
        reader.terminal_sink = lambda *args: {'status':'applied'}
    def timeout(*args): raise socket.timeout('timed out')
    setattr(client, endpoint, timeout)
    with pytest.raises(socket.timeout): reader()
    assert store._motion_slicer_profile is verified
    setattr(client, endpoint, original)
    assert reader() == [client.job]


@pytest.mark.parametrize('plan_state', ['missing', 'quarantined'])
def test_http_timeout_without_trusted_bound_plan_still_invalidates(bench, plan_state):
    store, catalog, fleet, adapter = bench
    life = MotionLifecycle(adapter); e = evidence(store)
    started = life.start('a', filename='job.gcode', observed_at=1010.,
                        capture_id=e['capture_id'], epoch=e['epoch'], start=e['start'], channels=['0'])
    if plan_state == 'quarantined':
        e['profile']['file_sha256'] = 'a'*64
        life.recovery_profile('a', history(), e['profile'])
        catalog.db.execute('UPDATE uid_recovery_profiles SET quarantined=1')
        catalog.db.commit()
    life.history_timeout('a', 'timed out')
    assert adapter.service.accounting.job(started['job_key'])['mapping_valid'] == 0
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
