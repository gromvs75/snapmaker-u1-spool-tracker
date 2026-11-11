import time
import sqlite3
import pytest
from test_uid_manual import manual, assign, begin
from tracker_uid_accounting import AccountingConflict, UidAccounting
from tracker_uid_catalog import UidCatalog


def setup_resolution(manual):
    c,a,f=manual;assign(a,f);key=begin(a,f)
    c.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?',(key,));c.db.commit()
    version=a.resolution_version(a.job(key))
    observation={'state':'cancelled','checked_at':time.monotonic(),'connection_token':c.connection_token(f['a'])}
    return c,a,f,key,version,observation


def resolve(a,f,key,version,obs,**kw):
    args={'confirmed':True,'accept_unaccounted':True};args.update(kw)
    return a.resolve_interrupted(key,version,obs,f,**args)


def test_resolution_durable_idempotent_and_late_usage_fenced(manual):
    c,a,f,key,version,obs=setup_resolution(manual)
    source=a.job(key)['source']
    result=resolve(a,f,key,version,obs)
    assert resolve(a,f,key,version,obs)==result
    assert a.job(key)['state']=='resolved'
    assert c.db.execute('SELECT confirmed FROM manual_assignments').fetchone()[0]==0
    with pytest.raises(AccountingConflict):a.apply(key,1,{'0':298},state='cancelled',source=source,basis='motion_estimate')
    path=c.db.execute('PRAGMA database_list').fetchone()[2]
    c.close();c2=UidCatalog(path)
    try:
        a2=UidAccounting(c2)
        assert resolve(a2,f,key,version,obs)==result
        assert c2.db.execute('SELECT count(*) FROM uid_manual_resolutions').fetchone()[0]==1
        assert c2.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0
        assert c2.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000
    finally:c2.close()


@pytest.mark.parametrize('fault',['unchecked','unaccepted','printing','paused','unknown','stale','connection','offline','version','healthy','terminal'])
def test_resolution_rejects_unsafe_or_stale(manual,fault):
    c,a,f,key,v,obs=setup_resolution(manual)
    if fault in ('printing','paused','unknown'):obs['state']=fault
    if fault=='stale':obs['checked_at']-=10
    if fault=='connection':f['a']['generation']=f['a'].get('generation',0)+1
    if fault=='offline':f['a']['state']='offline'
    if fault=='version':v='old'
    if fault=='healthy':c.db.execute('UPDATE uid_jobs SET mapping_valid=1');c.db.commit();v=a.resolution_version(a.job(key))
    if fault=='terminal':c.db.execute("UPDATE uid_jobs SET state='completed'");c.db.commit();v=a.resolution_version(a.job(key))
    with pytest.raises(AccountingConflict):resolve(a,f,key,v,obs,confirmed=fault!='unchecked',accept_unaccounted=fault!='unaccepted')
    assert c.db.execute('SELECT count(*) FROM uid_manual_resolutions').fetchone()[0]==0
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000


def test_resolution_transaction_rolls_back(manual):
    c,a,f,key,v,obs=setup_resolution(manual)
    c.db.execute("CREATE TRIGGER fail_resolution BEFORE UPDATE ON uid_jobs BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):resolve(a,f,key,v,obs)
    assert a.job(key)['state']=='active'
    assert c.db.execute('SELECT count(*) FROM uid_manual_resolutions').fetchone()[0]==0
    assert c.db.execute('SELECT confirmed FROM manual_assignments').fetchone()[0]==1


def test_resolution_keeps_previously_accounted_usage(manual):
    c,a,f=manual;assign(a,f);key=begin(a,f);source=a.job(key)['source']
    a.apply(key,1,{'0':100},state='active',source=source,basis='motion_estimate')
    c.db.execute('UPDATE uid_jobs SET mapping_valid=0');c.db.commit()
    obs={'state':'complete','checked_at':time.monotonic(),'connection_token':c.connection_token(f['a'])}
    resolve(a,f,key,a.resolution_version(a.job(key)),obs)
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==499900
    assert a.apply(key,1,{'0':100},state='active',source=source,basis='motion_estimate')=='duplicate'
    with pytest.raises(AccountingConflict):a.apply(key,2,{'0':200},state='completed',source=source,basis='motion_estimate')
