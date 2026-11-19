"""Synthetic tangle/error/resume histories; never connect to a printer."""
import copy
import json
import pytest

from test_uid_motion_adapter import bench, evidence, history
from tracker_uid_motion_lifecycle import MotionLifecycle
from tracker_uid_history_review import HistoryReview


def test_same_history_identity_error_then_completed_accounts_once(bench):
    store, catalog, fleet, adapter = bench
    life = MotionLifecycle(adapter)
    e = evidence(store)
    e['terminal_state'] = 'completed'
    key = life.start('a', filename='job.gcode', observed_at=1010.,
                     capture_id=e['capture_id'], epoch=e['epoch'], start=e['start'], channels=['0'])['job_key']
    life.history('a', [history()])
    life.history('a', [history('error')])
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    life.history('a', [history()])  # continuing the SAME print
    life.terminal('a', e)
    result = life.history('a', [history('completed')])[0]
    assert result['status'] == 'applied', result
    for status in ('error', 'in_progress', 'completed', 'completed'):
        life.history('a', [history(status)])
    assert catalog.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 1
    assert catalog.spool('04112233')['remaining_mg'] == 499702
    assert json.loads(catalog.db.execute('SELECT history FROM uid_motion_captures WHERE key=?',(key,)).fetchone()[0])['status'] == 'completed'


def test_terminal_failed_capture_can_be_reviewed_without_disconnect(bench):
    store, catalog, fleet, adapter = bench
    life = MotionLifecycle(adapter)
    e = evidence(store)
    key = life.start('a', filename='job.gcode', observed_at=1010.,
                     capture_id=e['capture_id'], epoch=e['epoch'], start=e['start'], channels=['0'])['job_key']
    life.history('a', [history('completed')])
    review = HistoryReview(adapter.service.accounting)
    assert review.detail(key)['can_review']


def test_history_only_manual_recovery_once_and_no_current_slot_guess(bench):
    store, catalog, fleet, adapter = bench
    MotionLifecycle(adapter)
    review = HistoryReview(adapter.service.accounting)
    review.observe_history('a', [history('error')])
    review.observe_history('a', [history('completed')])
    saved = review.unaccounted_history('a')[0]
    assert saved['status'] == 'completed'
    key = review.prepare_history(saved['history_key'])['job_key']
    assert review.prepare_history(saved['history_key'])['job_key'] == key
    detail = review.detail(key)
    assert detail['can_review'] and not detail['plan']
    assert all(s['suggested_additional_mg'] is None for s in detail['candidates'])
    sid = catalog.spool('04AABBCC')['spool_id']  # explicit choice, not T0's current spool
    request = dict(job_key=key, action='account', expected_revision=detail['revision'],
                   request_id='history-only-manual-1', confirmed=True, completed=True,
                   allocations_mg={sid:3500}, note='', fleet={})
    assert review.decide(**request)['status'] == 'saved'
    assert review.decide(**request)['status'] == 'duplicate'
    review.observe_history('a', [history('error'), history('completed')])
    assert not review.unaccounted_history('a')
    assert not review.detail(key)['can_review']
    assert catalog.spool('04AABBCC')['remaining_mg'] == 296500
    assert catalog.spool('04112233')['remaining_mg'] == 500000
    assert catalog.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 1


@pytest.mark.parametrize('state',['printing','paused'])
def test_terminal_history_does_not_allow_manual_debit_while_printer_runs(bench,state):
    import time
    store,catalog,fleet,adapter=bench
    MotionLifecycle(adapter);review=HistoryReview(adapter.service.accounting)
    review.observe_history('a',[history('error')])
    key=review.prepare_history(review.unaccounted_history('a')[0]['history_key'])['job_key']
    d=review.detail(key);sid=d['candidates'][0]['spool_id']
    observation=dict(state=state,checked_at=time.monotonic(),connection_token=catalog.connection_token(fleet.snapshot()['a']))
    with pytest.raises(ValueError,match='Принтер печатает'):
        review.decide(key,'account',d['revision'],'live-state-block',True,{sid:1000},'',True,
                      fleet=fleet.snapshot(),observation=observation)
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()


def test_prepare_reuses_bound_job_and_never_replaces_original_spools(bench):
    store,catalog,fleet,adapter=bench;life=MotionLifecycle(adapter);e=evidence(store)
    key=life.start('a',filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])['job_key']
    life.history('a',[history('completed')]);review=HistoryReview(adapter.service.accounting)
    review.observe_history('a',[history('completed')])
    hk=catalog.db.execute('SELECT history_key FROM uid_printer_history').fetchone()[0]
    assert review.prepare_history(hk)['job_key']==key
    assert len(review.detail(key)['candidates'])==1
    assert catalog.db.execute('SELECT count(*) FROM uid_jobs').fetchone()[0]==1


def test_new_history_identity_after_error_is_not_automatically_merged(bench):
    store,catalog,fleet,adapter=bench;life=MotionLifecycle(adapter);e=evidence(store)
    key=life.start('a',filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])['job_key']
    life.history('a',[history('error')])
    e['terminal_state']='completed';life.terminal('a',e)
    life.history('a',[history('error'),history('completed',ident='new-after-error',start=1100.)])
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    review=HistoryReview(adapter.service.accounting)
    assert review.detail(key)['can_review']


def test_manual_history_fences_late_automatic_capture(bench):
    store,catalog,fleet,adapter=bench;life=MotionLifecycle(adapter);review=HistoryReview(adapter.service.accounting)
    review.observe_history('a',[history('completed')])
    manual=review.prepare_history(review.unaccounted_history('a')[0]['history_key'])['job_key']
    e=evidence(store);e['terminal_state']='completed'
    other=life.start('a',filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])['job_key']
    result=life.history('a',[history('completed')])[0]
    assert result['status']=='review' and 'manual accounting' in result['reason']
    life.terminal('a',e)
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    assert other!=manual and adapter.service.accounting.job(other)['mapping_valid']==0
