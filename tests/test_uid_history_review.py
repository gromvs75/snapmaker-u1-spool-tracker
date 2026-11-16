import copy
import pytest
from test_uid_motion_adapter import bench, history
from test_uid_recovery import prepare
from tracker_uid_history_review import HistoryReview


def setup_review(bench):
    life,key,c=prepare(bench)
    review=HistoryReview(life.adapter.service.accounting)
    return life,key,c,review


def args(review,key,action='account',amount=750):
    d=review.detail(key)
    return dict(job_key=key,action=action,expected_revision=d['revision'],request_id='manual-test-001',confirmed=True,
        allocations_mg={d['candidates'][0]['spool_id']:amount},note='Проверено пользователем',completed=True,fleet={})


def test_saved_plan_without_terminal_history_or_network(bench):
    life,key,c,review=setup_review(bench)
    d=review.detail(key)
    assert d['plan'][0]['planned_mg']==1000
    assert d['plan'][0]['channel']=='0'
    assert d['accounted_mg']==0
    request=args(review,key)
    assert review.decide(**request)['additional_mg']==750 # edited, not entire plan
    assert review.decide(**request)['status']=='duplicate'
    life.history('a',[history('completed')]);life.history('a',[history('completed')])
    assert c.db.execute('SELECT sum(delta_mg) FROM uid_debits').fetchone()[0]==750
    assert HistoryReview(life.adapter.service.accounting).decide(**request)['status']=='duplicate'
    with pytest.raises(ValueError):review.decide(**dict(request,note='Изменено'))


def test_partial_debit_suggests_only_remaining_and_uses_new_sequence(bench):
    life,key,c,review=setup_review(bench)
    sid=review.detail(key)['candidates'][0]['spool_id']
    with c.db:
        c.db.execute('INSERT INTO uid_debits VALUES(?,?,?,?)',(key,3,sid,300))
        c.db.execute('UPDATE uid_jobs SET last_sequence=3 WHERE job_key=?',(key,))
        c.db.execute('UPDATE uid_spools SET remaining_mg=remaining_mg-300 WHERE spool_id=?',(sid,))
    d=review.detail(key)
    assert d['candidates'][0]['suggested_additional_mg']==700
    review.decide(**args(review,key,amount=650))
    assert c.db.execute('SELECT sum(delta_mg) FROM uid_debits').fetchone()[0]==950
    assert c.db.execute('SELECT max(sequence) FROM uid_debits').fetchone()[0]==4


def test_defer_and_close_without_debit_persist(bench):
    life,key,c,review=setup_review(bench)
    review.decide(**args(review,key,'defer',0))
    assert review.detail(key)['job']['state']=='active'
    request=args(review,key,'close',0);request['request_id']='manual-test-002'
    review.decide(**request)
    life.history('a',[history('completed')])
    assert review.detail(key)['job']['state']=='resolved'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


@pytest.mark.parametrize('fault',['stale','negative','bool','live','no_confirm','no_completed','excess','foreign'])
def test_rejects_without_any_mutation(bench,fault):
    life,key,c,review=setup_review(bench);request=args(review,key)
    if fault=='stale':request['expected_revision']='old'
    if fault in ('negative','bool','excess'):request['allocations_mg']={next(iter(request['allocations_mg'])):{'negative':-1,'bool':True,'excess':99999999}[fault]}
    if fault=='foreign':request['allocations_mg']={'unrelated':100}
    if fault=='live':request['fleet']={'a':{'state':'ready'}}
    if fault=='no_confirm':request['confirmed']=False
    if fault=='no_completed':request['completed']=False
    with pytest.raises(ValueError):review.decide(**request)
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_swaps_never_default_full_plan_to_original(bench):
    from test_uid_replacements import setup,swap
    life,key,status,c,fleet=setup(bench);life.disconnected('a','sleep');swap(life,status,fleet)
    review=HistoryReview(life.adapter.service.accounting)
    assert review.detail(key)['replacements']
    assert all(s['suggested_additional_mg'] is None for s in review.detail(key)['candidates'])


def test_uncertain_remote_local_amount_not_repeated(bench):
    from tracker_uid_library import Library
    life,key,c,review=setup_review(bench);Library(life.adapter.service.accounting)
    sid=review.detail(key)['candidates'][0]['spool_id']
    with c.db:
        c.db.execute("INSERT INTO uid_remote_outbox VALUES(?,?,?,? ,?,?,'uncertain')",(key,0,sid,'http://127.0.0.1:19872',1,300))
    with pytest.raises(ValueError,match='неопределённые'):review.decide(**args(review,key))
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_connected_idle_requires_fresh_server_observation(bench):
    import time
    from tracker_uid_catalog import UidCatalog
    life,key,c,review=setup_review(bench)
    request=args(review,key);request['fleet']=life.adapter.service.fleet.snapshot()
    snapshot=request['fleet']['a']
    observation=dict(state='complete',checked_at=time.monotonic(),connection_token=UidCatalog.connection_token(snapshot))
    with pytest.raises(ValueError):review.decide(**request,observation=dict(observation,state='paused'))
    with pytest.raises(ValueError):review.decide(**request,observation=dict(observation,checked_at=time.monotonic()-5))
    assert review.decide(**request,observation=observation)['status']=='saved'


def test_manual_receipt_restore_keeps_idempotency_and_holds_remote(bench):
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    from tracker_uid_backup import export,validate,restore
    life,key,c,review=setup_review(bench)
    Library(life.adapter.service.accounting);Delivery(life.adapter.service.accounting)
    sid=review.detail(key)['candidates'][0]['spool_id']
    with c.db:c.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(sid,'http://127.0.0.1:19872',1))
    request=args(review,key);review.decide(**request)
    package=export(c.db);v=validate(package,c.db);restore(package,c.db,v['current_revision'])
    assert review.decide(**request)['status']=='duplicate'
    life.history('a',[history('completed')])
    assert review.detail(key)['accounted_mg']==750
    assert c.db.execute('SELECT state FROM uid_remote_outbox').fetchone()[0]=='uncertain'
