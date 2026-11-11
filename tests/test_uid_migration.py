import copy
import importlib.util
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'dev/labs/uid_migration_bench'))
import legacy_storage_fixture as fixed_storage
from tracker_uid_migration import BenchMigration
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting, TrackerUidService, AccountingConflict
from tracker_uid_motion_adapter import UidMotionAdapter
from tracker_uid_motion_lifecycle import MotionLifecycle
from test_uid_accounting import snapshot
from filelock import Timeout


@pytest.fixture
def migration(tmp_path):
    (tmp_path/'.tracker-migration-bench').write_text('synthetic-only')
    (tmp_path/'legacy').mkdir()
    cfg={'host':'bench.local','port':7125,'enabled':True,'guard_mode':'warn'}
    plan={'filename':'fixture.gcode','sha256':'a'*64,'size':10,'weights':[10,0,0,0],
          'spool_ids':['s','','',''],'created_at':900,'status':'committed','printer':cfg}
    data={'schema_version':5,'printer':cfg,'spools':{'s':{'name':'Tagged','material':'PLA','remaining_g':470},
         'manual':{'name':'Untagged','material':'PETG','remaining_g':123.456}},
         'slots':{'1':'s','2':'manual','3':'','4':''},'plans':{'p':plan},'runs':{}}
    for i,status in enumerate(['committed','committed','committed','active','review','cancelled','error']):
        run={'job_id':str(i),'plan_id':'p','start_time':1000+i,'filename':'fixture.gcode','status':status}
        if i==0:run.update(physical_weights=[10,0,0,0],physical_spool_ids=['s','','',''],tool_mapping=[0,1,2,3])
        if i==1:run.update(accounting_method='manual_review',manual_consumption={'s':10})
        if i==2:run.update(accounting_method='motion_estimate',motion_consumption={'s':10},motion_capture_id='c',motion_epoch='e',terminal_status='cancelled')
        data['runs']['old-'+str(i)]=run
    path=tmp_path/'legacy/spools_u1.json';path.write_text(json.dumps(data,indent=2)+'\n')
    return BenchMigration(tmp_path,validator=fixed_storage.validate_db),data,path.read_bytes()


def perform(m, **kw): return m.migrate({'bench.local:7125':'printer-a'},{'s':'04112233'},**kw)


def test_backup_history_fences_and_exact_restore(migration):
    m,data,raw=migration
    report=perform(m)
    assert report['history_fences']==7 and report['automatic_spools']==1
    assert m.backup.read_bytes()==raw
    assert json.loads(m.source.read_bytes())['schema_version']==2000
    assert perform(m)==report
    c=UidCatalog(m.target)
    try:
        a=UidAccounting(c)
        assert c.spool('04112233')['spool_id']=='s'
        assert c.spool('04112233')['remaining_mg']==470000
        assert c.db.execute('SELECT payload FROM migration_source').fetchone()[0]==raw
        assert json.loads(c.db.execute("SELECT payload FROM legacy_spools WHERE spool_id='manual'").fetchone()[0])==data['spools']['manual']
        class Fleet:
            def snapshot(self):return {'printer-a':snapshot('printer-a',{'0':'04112233'})}
        life=MotionLifecycle(UidMotionAdapter(TrackerUidService(Fleet(),c)))
        jobs=[dict(job_id=str(i),start_time=float(1000+i),filename='fixture.gcode',status='completed') for i in range(7)]
        for _ in range(3):
            result=life.history('printer-a',jobs)
            assert [r['status'] for r in result]==['legacy_duplicate']*3+['review']*4
        with pytest.raises(AccountingConflict):a.begin('printer-a','0','1000.0',['0'],'new',Fleet().snapshot())
        assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0
        with pytest.raises(Timeout):m.restore_legacy()
    finally:c.close()
    assert m.restore_legacy()['mode']=='restored'
    assert m.source.read_bytes()==raw
    with pytest.raises(ValueError):UidCatalog(m.target)


@pytest.mark.parametrize('failure',['backup','transaction','stage','fence','publish'])
def test_interrupted_migration_restore_is_exact(migration,failure):
    m,data,raw=migration
    with pytest.raises(RuntimeError):perform(m,fail=failure)
    with pytest.raises(ValueError):UidCatalog(m.target)
    assert m.restore_legacy()['mode']=='restored'
    assert m.source.read_bytes()==raw


def test_restore_rejects_corrupt_backup(migration):
    m,_,_=migration;perform(m);m.backup.write_text('{}')
    with pytest.raises(ValueError,match='checksum'):m.restore_legacy()
    assert json.loads(m.source.read_bytes())['schema_version']==2000


def test_restore_rejects_new_accounting_and_legacy_writer_cannot_write(migration):
    m,_,_=migration;perform(m)
    # Validate the fixed legacy implementation, not an invented marker-aware writer.
    spec=importlib.util.spec_from_file_location('fixed_storage',ROOT/'dev/labs/uid_migration_bench/legacy_storage_fixture.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    store=mod.Store(m.source.parent)
    with pytest.raises(mod.StorageError):store.update(lambda db:db['spools']['s'].update(remaining_g=1))
    c=UidCatalog(m.target)
    try:
        a=UidAccounting(c);fleet={'printer-a':snapshot('printer-a',{'0':'04112233'})}
        k=a.begin('printer-a','new','2000',['0'],'new',fleet)
        a.apply(k,1,{'0':1000},state='completed',source='new',basis='motion_estimate')
    finally:c.close()
    with pytest.raises(ValueError,match='New accounting'):m.restore_legacy()
    c=UidCatalog(m.target)
    try:assert c.spool('04112233')['remaining_mg']==469000
    finally:c.close()


def test_duplicate_uid_and_unmapped_printer_fail_before_source_change(migration):
    m,data,raw=migration
    with pytest.raises(ValueError):m.migrate({'bench.local:7125':'printer-a'},{'s':'04112233','manual':'04112233'})
    with pytest.raises(KeyError):m.migrate({}, {'s':'04112233'})
    assert m.source.read_bytes()==raw and not m.backup.exists()


def test_outbox_preserved_and_pending_sends_held(migration):
    import spoolman_bridge as bridge
    m,data,raw=migration
    state=bridge.blank();state.update(url='http://127.0.0.1:19999',mode='send',epoch='e')
    for status in ('pending','sending','uncertain','sent','external','resolved'):
        state['outbox'][status]={'state':status,'job':'old-0','local_id':'remote','url':state['url'],'spool_id':1,'grams':10,'created_at':1000}
    data['spoolman']=state;m.source.write_text(json.dumps(data))
    perform(m)
    c=UidCatalog(m.target)
    try:
        rows={r['operation_id']:dict(r) for r in c.db.execute('SELECT * FROM legacy_outbox')}
        assert set(rows)==set(state['outbox'])
        for k,op in state['outbox'].items():
            assert json.loads(rows[k]['payload'])==op
            assert rows[k]['state']==('held' if k in ('pending','sending','uncertain') else k)
    finally:c.close()
    with pytest.raises(ValueError,match='remote operations'):m.restore_legacy()


@pytest.mark.parametrize('which',['legacy_lock','remote_lock'])
def test_running_old_writer_or_spoolman_blocks_migration(migration,which):
    from filelock import FileLock
    m,_,raw=migration
    lock=FileLock(getattr(m,which).lock_file,timeout=0)
    with lock:
        with pytest.raises(Timeout):perform(m)
    assert m.source.read_bytes()==raw and not m.backup.exists()


def test_queue_owner_replays_migrated_history_after_reopen(migration):
    from tracker_uid_runtime import AccountingOwner
    m,_,_=migration;perform(m)
    class Fleet:
        def snapshot(self):return {}
    for _ in range(2):
        owner=AccountingOwner(m.target,Fleet())
        try:
            rows=owner.call('history','printer-a',[dict(job_id='2',start_time=1002.0,filename='fixture.gcode',status='cancelled')])
            assert rows[0]['status']=='legacy_duplicate'
            assert owner.call('inspect')['debits']==[]
            with pytest.raises(Timeout):m.restore_legacy()
        finally:owner.close()


def test_corrupt_target_not_blindly_rolled_back(migration):
    m,_,_=migration;perform(m);m.target.write_bytes(b'broken sqlite')
    with pytest.raises(Exception):m.restore_legacy()
    assert json.loads(m.source.read_bytes())['schema_version']==2000


def test_backup_before_manifest_crash_recovers_original(migration):
    m,_,raw=migration;m.backup.write_bytes(raw)
    assert m.restore_legacy()['mode']=='restored'
    assert m.source.read_bytes()==raw
