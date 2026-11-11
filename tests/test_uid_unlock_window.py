import time
import pytest
from test_uid_resolution import manual, setup_resolution
from test_uid_manual import assign, begin
from tracker_uid_accounting import AccountingConflict, UidAccounting
from tracker_uid_catalog import UidCatalog


def unlock(a,f,key,v,obs,mode='15_minutes'):
    return a.resolve_interrupted(key,v,obs,f,confirmed=True,accept_unaccounted=True,mode=mode)


def test_expiry_relocks_and_replay_does_not_extend(manual,monkeypatch):
    c,a,f,key,v,obs=setup_resolution(manual)
    now=time.time();monkeypatch.setattr('tracker_uid_accounting.time.time',lambda:now)
    r=unlock(a,f,key,v,obs);assert r['deadline']==now+900
    now+=901
    assert a.unlock_state(key)['expired']
    assert unlock(a,f,key,v,obs)==r
    with pytest.raises(AccountingConflict):assign(a,f)
    with pytest.raises(AccountingConflict):a.transfer_manual('manual-id','a','0','b','1',c.db.execute('select version from manual_assignments').fetchone()[0],'expired-transfer',f,confirmed=True)
    new_v=a.resolution_version(a.job(key));renewed=unlock(a,f,key,new_v,obs)
    assert renewed['deadline']==now+900
    assert c.db.execute('SELECT count(*) FROM uid_unlock_attempts').fetchone()[0]==2
    assert c.db.execute('SELECT count(*) FROM uid_manual_resolutions').fetchone()[0]==1
    assign(a,f);assert a.unlock_state(key)['completed']
    now+=901;assert not a.unlock_state(key)['expired']
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000


@pytest.mark.parametrize('mode',['15_minutes','until_assignment'])
def test_confirm_completes_window_and_new_job_is_allowed(manual,mode):
    c,a,f,key,v,obs=setup_resolution(manual);unlock(a,f,key,v,obs,mode)
    with pytest.raises(AccountingConflict):begin(a,f,job='next')
    assign(a,f);assert a.unlock_state(key)['completed']
    begin(a,f,job='next')
    with pytest.raises(AccountingConflict):a.apply(key,1,{'0':999},state='cancelled',source=a.job(key)['source'],basis='motion_estimate')
    assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0


def test_pending_deadline_survives_restart(manual,monkeypatch):
    c,a,f,key,v,obs=setup_resolution(manual);r=unlock(a,f,key,v,obs)
    path=c.db.execute('PRAGMA database_list').fetchone()[2];c.close()
    monkeypatch.setattr('tracker_uid_accounting.time.time',lambda:r['deadline']+1)
    c2=UidCatalog(path)
    try:
        a2=UidAccounting(c2);assert a2.unlock_state(key)['expired']
        assert unlock(a2,f,key,v,obs)==r
        with pytest.raises(AccountingConflict):assign(a2,f)
    finally:c2.close()


def test_mode_change_on_same_request_rejected(manual):
    c,a,f,key,v,obs=setup_resolution(manual);unlock(a,f,key,v,obs)
    with pytest.raises(AccountingConflict):unlock(a,f,key,v,obs,'until_assignment')


def test_until_assignment_has_no_timer(manual,monkeypatch):
    c,a,f,key,v,obs=setup_resolution(manual);unlock(a,f,key,v,obs,'until_assignment')
    monkeypatch.setattr('tracker_uid_accounting.time.time',lambda:time.monotonic()+10**12)
    assert not a.unlock_state(key)['expired']
    assert a.unlock_state(key)['deadline'] is None
    assign(a,f);assert a.unlock_state(key)['completed']


def test_partial_transfer_does_not_allow_print_before_all_confirmed(manual,monkeypatch):
    c,a,f=manual;assign(a,f)
    c.register_manual('Second',500000,spool_id='second');assign(a,f,'a','1','second')
    key=a.begin('a','two','1000',['0','1'],'capture',f)
    c.db.execute('UPDATE uid_jobs SET mapping_valid=0');c.db.commit()
    obs={'state':'cancelled','checked_at':time.monotonic(),'connection_token':c.connection_token(f['a'])}
    r=unlock(a,f,key,a.resolution_version(a.job(key)),obs)
    version=c.db.execute("SELECT version FROM manual_assignments WHERE spool_id='manual-id'").fetchone()[0]
    a.transfer_manual('manual-id','a','0','b','2',version,'partial',f,confirmed=True)
    assert not a.unlock_state(key)['completed']
    with pytest.raises(AccountingConflict):begin(a,f,'b','2','unsafe')
    monkeypatch.setattr('tracker_uid_accounting.time.time',lambda:r['deadline']+1)
    with pytest.raises(AccountingConflict):assign(a,f,'b','2')
    unlock(a,f,key,a.resolution_version(a.job(key)),obs)
    assert c.db.execute("SELECT confirmed FROM manual_assignments WHERE spool_id='manual-id'").fetchone()[0]==0
