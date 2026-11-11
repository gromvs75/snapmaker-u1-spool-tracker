import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting, AccountingConflict
from tracker_uid_runtime import AccountingOwner
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan

@pytest.fixture
def manual(tmp_path):
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c)
    s=c.register_manual('Manual',500000,spool_id='manual-id')
    f={'a':snapshot('a',{}),'b':snapshot('b',{})}
    yield c,a,f
    c.close()

def assign(a,f,pid='a',ch='0',sid='manual-id'):
    return a.assign_manual(pid,ch,sid,f,confirmed=True)
def begin(a,f,pid='a',ch='0',job='j'):
    return a.begin(pid,job,'1000',[ch],'capture',f)
def debit(a,k,n=1000,state='completed'):
    return a.apply(k,1,{'0':n},state=state,source='capture',basis='motion_estimate')

def test_manual_transfer_and_duplicate_preserve_id_and_balance(manual):
    c,a,f=manual;assign(a,f)
    k=begin(a,f);a.observe(f);assert debit(a,k)=='applied'
    a.release_manual('a','0');assign(a,f,'b','2')
    k2=begin(a,f,'b','2','next')
    a.apply(k2,1,{'2':2000},state='cancelled',source='capture',basis='motion_estimate')
    assert debit(a,k)=='duplicate'
    row=c.db.execute("SELECT * FROM uid_spools WHERE spool_id='manual-id'").fetchone()
    assert row['uid'] is None and row['remaining_mg']==497000
    assert c.register_manual('Changed',1,spool_id='manual-id')['remaining_mg']==497000

@pytest.mark.parametrize('fault',['gap','restart_token','tag','release'])
def test_continuity_loss_is_permanent(manual,fault):
    c,a,f=manual;assign(a,f);k=begin(a,f)
    if fault=='gap':f['a']['state']='offline'
    if fault=='restart_token':f['a']['generation']=2
    if fault=='tag':f['a']=snapshot('a',{'0':'04112233'})
    if fault=='release':a.release_manual('a','0')
    a.observe(f);f['a']=snapshot('a',{});a.observe(f)
    with pytest.raises(AccountingConflict):debit(a,k)
    assert a.job(k)['mapping_valid']==0


def test_assignment_requires_confirmation_and_no_conflict(manual):
    c,a,f=manual
    with pytest.raises(ValueError):a.assign_manual('a','0','manual-id',f)
    assign(a,f)
    with pytest.raises(AccountingConflict):assign(a,f,'b','1')
    k=begin(a,f)
    with pytest.raises(AccountingConflict):assign(a,f)
    a.release_manual('a','0')
    with pytest.raises(AccountingConflict):assign(a,f,'b','1')
    debit(a,k,0,'cancelled')
    assign(a,f,'b','1')


def test_uid_conflict_never_silently_overrides_manual(manual):
    c,a,f=manual;c.register('04112233','Tagged',10000);assign(a,f)
    f['a']=snapshot('a',{'0':'04112233'})
    assert all(not r['usable'] for r in a.observe(f))
    with pytest.raises(AccountingConflict):begin(a,f)
    a.release_manual('a','0')
    assert begin(a,f)


def test_reopen_requires_confirmation(tmp_path):
    path=tmp_path/'db';c=UidCatalog(path);a=UidAccounting(c)
    c.register_manual('Manual',1000,spool_id='manual-id');f={'a':snapshot('a',{})};assign(a,f);c.close()
    c=UidCatalog(path);a=UidAccounting(c)
    try:
        with pytest.raises(AccountingConflict):begin(a,f)
        assign(a,f);assert begin(a,f)
    finally:c.close()


def test_manual_evidence_through_queue_and_history_reopen(tmp_path):
    store,*_=setup_plan(tmp_path)
    class Fleet:
        def snapshot(self):return {'a':snapshot('a',{})}
    path=tmp_path/'queue.sqlite';owner=AccountingOwner(path,Fleet())
    e=evidence(store);e['terminal_state']='cancelled'
    h=dict(job_id='real-history',start_time=1010.0,filename='job.gcode',status='cancelled')
    try:
        owner.call('register_manual','Manual',500000,spool_id='manual-id',details={'material':'PLA'})
        owner.call('assign_manual','a','0','manual-id',confirmed=True)
        e['start']=owner.call('inventory_snapshot','a')
        result=owner.call('start','a',filename='job.gcode',observed_at=1010.0,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
        assert result['status']=='started'
        owner.call('terminal','a',e)
        assert owner.call('history','a',[h])[0]['status']=='applied'
        assert owner.call('inspect')['spools'][0]['remaining_mg']==499702
    finally:owner.close()
    owner=AccountingOwner(path,Fleet())
    try:
        assert owner.call('history','a',[h])[0]['status']=='duplicate'
        assert len(owner.call('inspect')['debits'])==1
        assert owner.call('inspect')['manual_assignments'][0]['confirmed']==0
    finally:owner.close()


def test_schema_upgrade_keeps_existing_tagged_ledger(tmp_path):
    import sqlite3
    path=tmp_path/'old';db=sqlite3.connect(path)
    db.execute('CREATE TABLE uid_spools (spool_id TEXT PRIMARY KEY, uid TEXT NOT NULL UNIQUE, name TEXT NOT NULL, remaining_mg INTEGER NOT NULL)')
    db.execute("INSERT INTO uid_spools VALUES('tagged','04112233','Tagged',10000)")
    db.execute('CREATE TABLE preserved_refs (spool_id TEXT REFERENCES uid_spools(spool_id))')
    db.execute("INSERT INTO preserved_refs VALUES('tagged')")
    db.commit();db.close()
    c=UidCatalog(path);a=UidAccounting(c)
    try:
        assert c.spool('04112233')['remaining_mg']==10000
        assert c.register_manual('Manual',2000)['uid'] is None
        assert c.db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert c.db.execute('SELECT spool_id FROM preserved_refs').fetchone()[0]=='tagged'
    finally:c.close()


def test_migration_manual_slots_are_working_but_unconfirmed(tmp_path):
    from test_uid_migration import fixed_storage
    from tracker_uid_migration import BenchMigration
    import json
    (tmp_path/'.tracker-migration-bench').write_text('synthetic-only');(tmp_path/'legacy').mkdir()
    data=fixed_storage.empty_db();data['printer']['host']='bench.local'
    data['spools']={'manual-id':{'name':'Manual','remaining_g':123.456,'material':'PLA','color':'#ff0000'}}
    data['slots']['1']='manual-id'
    (tmp_path/'legacy/spools_u1.json').write_text(json.dumps(data))
    m=BenchMigration(tmp_path,validator=fixed_storage.validate_db)
    receipt=m.migrate({'bench.local:7125':'a'}, {})
    assert receipt['local_spools']==1 and receipt['automatic_spools']==0
    c=UidCatalog(m.target);a=UidAccounting(c);f={'a':snapshot('a',{})}
    try:
        with pytest.raises(AccountingConflict):begin(a,f)
        assign(a,f)
        model=c.inventory_snapshot('a',f)
        assert model['slots']['1']=='manual-id'
        assert model['spools']['manual-id']['color']=='#ff0000'
        k=begin(a,f);a.observe(f);debit(a,k)
        assert c.inventory_snapshot('a',f)['spools']['manual-id']['remaining_g']==122.456
    finally:c.close()


def test_collector_model_store_reads_current_manual_identity(tmp_path):
    from tracker_uid_runtime import ModelInventoryStore
    class Fleet:
        def snapshot(self):return {'a':snapshot('a',{})}
    owner=AccountingOwner(tmp_path/'db',Fleet())
    try:
        owner.call('register_manual','Manual',5000,spool_id='manual-id',details={'material':'PLA'})
        owner.call('assign_manual','a','0','manual-id',confirmed=True)
        store=ModelInventoryStore(owner,'a',tmp_path/'logs',{'enabled':True,'host':'127.0.0.1','port':18741})
        assert store.read()['slots']['1']=='manual-id'
        owner.call('release_manual','a','0')
        assert store.read()['slots']['1']==''
    finally:owner.close()


def test_archive_only_upgrade_keeps_original_rollback_safe(tmp_path):
    import json,sqlite3
    from test_uid_migration import fixed_storage
    from tracker_uid_migration import BenchMigration, digest, encode
    (tmp_path/'.tracker-migration-bench').write_text('synthetic-only');(tmp_path/'legacy').mkdir()
    data=fixed_storage.empty_db();data['spools']={'manual-id':{'name':'Manual','material':'PLA','remaining_g':123.456}}
    raw=json.dumps(data).encode();(tmp_path/'legacy/spools_u1.json').write_bytes(raw)
    m=BenchMigration(tmp_path,validator=fixed_storage.validate_db);m.migrate({}, {})
    # Reconstruct the previous archive-only target, before manual support.
    db=sqlite3.connect(m.target);db.execute('DELETE FROM uid_spools');db.commit();db.close()
    receipt=json.loads(m.receipt.read_bytes());receipt.pop('local_spools');receipt['inventory_sha']=digest(encode([]));m.receipt.write_bytes(encode(receipt))
    c=UidCatalog(m.target)
    try:assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==123456
    finally:c.close()
    assert m.restore_legacy()['mode']=='restored'
    assert m.source.read_bytes()==raw


def test_legacy_duplicate_manual_slots_require_resolution(tmp_path):
    import json
    from test_uid_migration import fixed_storage
    from tracker_uid_migration import BenchMigration
    (tmp_path/'.tracker-migration-bench').write_text('synthetic-only');(tmp_path/'legacy').mkdir()
    data=fixed_storage.empty_db();data['printer']['host']='bench.local'
    data['spools']={'manual-id':{'name':'Manual','material':'PLA','remaining_g':100}}
    data['slots'].update({'1':'manual-id','2':'manual-id'})
    (tmp_path/'legacy/spools_u1.json').write_text(json.dumps(data))
    m=BenchMigration(tmp_path,validator=fixed_storage.validate_db);m.migrate({'bench.local:7125':'a'}, {})
    c=UidCatalog(m.target);a=UidAccounting(c);f={'a':snapshot('a',{})}
    try:
        assert c.db.execute('SELECT count(*) FROM manual_assignments').fetchone()[0]==0
        assert c.db.execute('SELECT count(*) FROM manual_assignment_candidates').fetchone()[0]==2
        with pytest.raises(AccountingConflict):begin(a,f)
        assign(a,f);assert begin(a,f)
    finally:c.close()
