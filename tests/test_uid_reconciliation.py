import copy,time
import pytest
from test_uid_motion_adapter import bench
from test_uid_replacements import setup,swap,finish
from tracker_uid_reconciliation import Reconciliation
from tracker_uid_catalog import UidCatalog


def prepare(bench):
    life,key,status,c,fleet=setup(bench)
    life.disconnected('a','sleep');swap(life,status,fleet)
    assert finish(life,status)['status']=='review'
    review=Reconciliation(life.recovery,life.adapter.service.accounting)
    p=review.preview(key)
    obs=dict(state='complete',checked_at=time.monotonic(),connection_token=UidCatalog.connection_token(fleet.states['a']))
    allocations={c.spool('04112233')['spool_id']:500,c.spool('04CCCCDD')['spool_id']:2483}
    args=dict(job_key=key,expected_revision=p['revision'],allocations_mg=allocations,note='Проверено по сохранённой точке замены',request_id='review-001',confirmed=True,observation=obs,fleet=fleet.snapshot())
    return review,args,life,status,c,fleet


def test_review_is_readonly_atomic_and_retry_after_lost_response(bench):
    review,args,life,status,c,fleet=prepare(bench)
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    assert review.apply(**args)['status']=='applied'
    assert review.apply(**args)['status']=='duplicate'
    assert finish(life,status)['status']=='duplicate'
    assert c.spool('04112233')['remaining_mg']==19500
    assert c.spool('04CCCCDD')['remaining_mg']==97517
    assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==2
    again=Reconciliation(life.recovery,life.adapter.service.accounting)
    assert again.apply(**args)['status']=='duplicate'
    with pytest.raises(ValueError):again.apply(**dict(args,note='Изменённый повтор'))


@pytest.mark.parametrize('fault',['stale_balance','stale_time','connection','offline','printing','sum','negative','boolean','foreign_spool','confirm','note','resolved','quarantine'])
def test_reconciliation_rejects_unsafe_decision_without_any_debit(bench,fault):
    review,args,life,status,c,fleet=prepare(bench)
    if fault=='stale_balance':
        with c.db:c.db.execute('UPDATE uid_spools SET remaining_mg=remaining_mg+1')
    if fault=='stale_time':args['observation']['checked_at']-=4
    if fault=='connection':args['observation']['connection_token']='other'
    if fault=='offline':args['fleet']['a']['state']='offline'
    if fault=='printing':args['observation']['state']='printing'
    if fault in ('sum','negative','boolean'):args['allocations_mg'][next(iter(args['allocations_mg']))]={'sum':499,'negative':-1,'boolean':True}[fault]
    if fault=='foreign_spool':args['allocations_mg']['missing']=0
    if fault=='confirm':args['confirmed']=False
    if fault=='note':args['note']=''
    if fault=='resolved':
        with c.db:c.db.execute("UPDATE uid_jobs SET state='resolved'")
    if fault=='quarantine':
        with c.db:c.db.execute('UPDATE uid_recovery_profiles SET quarantined=1')
    with pytest.raises(ValueError):review.apply(**args)
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    assert not c.db.execute('SELECT * FROM uid_recovery_decisions').fetchall()


def test_insufficient_balance_rolls_back_all_and_spoolman_is_held(bench):
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    review,args,life,status,c,fleet=prepare(bench)
    Library(life.adapter.service.accounting);Delivery(life.adapter.service.accounting)
    with c.db:
        c.db.execute("UPDATE uid_spools SET remaining_mg=1000 WHERE uid='04CCCCDD'")
        for n,sid in enumerate(args['allocations_mg'],1):c.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(sid,'http://127.0.0.1:18899',n))
    args['expected_revision']=review.preview(args['job_key'])['revision']
    with pytest.raises(ValueError,match='остаток'):review.apply(**args)
    assert c.spool('04112233')['remaining_mg']==20000
    assert not c.db.execute('SELECT * FROM uid_remote_outbox').fetchall()
    with c.db:c.db.execute("UPDATE uid_spools SET remaining_mg=100000 WHERE uid='04CCCCDD'")
    args['expected_revision']=review.preview(args['job_key'])['revision']
    assert review.apply(**args)['status']=='applied'
    assert [r['state'] for r in c.db.execute('SELECT * FROM uid_remote_outbox')]==['held','held']
