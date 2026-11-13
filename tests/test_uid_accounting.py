import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting, TrackerUidService, AccountingConflict, mg, job_key


def snapshot(pid,bindings):
    return dict(printer_id=pid,state='ready',channels={str(i):{'state':'present' if str(i) in bindings else 'absent','uid':bindings.get(str(i))} for i in range(4)})

@pytest.fixture
def setup(tmp_path):
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c)
    c.register('04112233','Red',500000);c.register('04AABBCC','Green',300000)
    f={'a':snapshot('a',{'0':'04112233'}),'b':snapshot('b',{'1':'04AABBCC'})}
    yield c,a,f
    c.close()

def apply(a,k,seq,total,state='active',source='capture'):
    return a.apply(k,seq,total,state=state,source=source,basis='executed_gcode')

def test_parallel_cancel_transfer_and_replay(setup):
    c,a,f=setup
    ka=a.begin('a','same-id','start',['0'],'capture',f)
    kb=a.begin('b','same-id','start',['1'],'capture',f)
    assert ka!=kb
    apply(a,ka,1,{'0':29464});apply(a,kb,1,{'1':1997})
    apply(a,ka,2,{'0':30000},'cancelled');apply(a,kb,2,{'1':20000},'completed')
    assert apply(a,ka,2,{'0':30000},'cancelled')=='duplicate'
    assert apply(a,ka,3,{'0':30000},'cancelled')=='duplicate'
    f={'a':snapshot('a',{}),'b':snapshot('b',{'2':'04112233','1':'04AABBCC'})}
    kc=a.begin('b','next','next-start',['2'],'capture2',f)
    apply(a,kc,1,{'2':10000},'completed','capture2')
    assert apply(a,ka,2,{'0':30000},'cancelled')=='duplicate'
    assert c.spool('04112233')['remaining_mg']==460000
    assert c.spool('04AABBCC')['remaining_mg']==280000
    assert a.job(ka)['tools'][0]['spool_id']==c.spool('04112233')['spool_id']

def test_partial_progress_not_debited_again_on_cancel(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    for seq,value in [(1,1000),(2,1000),(3,3000)]:apply(a,k,seq,{'0':value})
    apply(a,k,4,{'0':4000},'cancelled')
    assert c.spool('04112233')['remaining_mg']==496000

def test_crash_rolls_back_debit_and_receipt(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    c.db.execute("CREATE TRIGGER crash BEFORE INSERT ON uid_usage_events BEGIN SELECT RAISE(ABORT,'injected interruption'); END")
    with pytest.raises(sqlite3.IntegrityError):apply(a,k,1,{'0':10000})
    assert c.spool('04112233')['remaining_mg']==500000
    assert a.job(k)['tools'][0]['used_mg']==0
    assert c.db.execute('SELECT COUNT(*) FROM uid_debits').fetchone()[0]==0
    c.db.execute('DROP TRIGGER crash')
    apply(a,k,1,{'0':10000})
    assert c.spool('04112233')['remaining_mg']==490000

def test_counter_reset_source_change_and_conflicting_replay(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f);apply(a,k,2,{'0':1000})
    assert apply(a,k,1,{'0':500})=='out_of_order'
    for seq,total,source in [(2,2000,'capture'),(3,500,'capture'),(3,2000,'new')]:
        with pytest.raises(AccountingConflict):apply(a,k,seq,{'0':total},source=source)
    assert c.spool('04112233')['remaining_mg']==499000

def test_active_spool_reserved_and_changed_identity_blocks_usage(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    moved={'a':snapshot('a',{}),'b':snapshot('b',{'2':'04112233'})}
    with pytest.raises(AccountingConflict):a.begin('b','j','s',['2'],'other',moved)
    a.observe(moved)
    with pytest.raises(AccountingConflict):apply(a,k,1,{'0':1000})
    apply(a,k,2,{'0':0},'cancelled') # release with known booked total; unknown remainder needs review
    assert c.spool('04112233')['remaining_mg']==500000

def test_age_only_does_not_unbind_running_job(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    f['a']['channels']['0']={'state':'stale','uid':None};a.observe(f)
    apply(a,k,1,{'0':1000})
    assert a.job(k)['mapping_valid']==1

def test_offline_gap_stays_invalid_after_reconnect(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    offline=copy.deepcopy(f);offline['a']['state']='offline';a.observe(offline);a.observe(f)
    with pytest.raises(AccountingConflict):apply(a,k,1,{'0':1000})

@pytest.mark.parametrize('totals',[{}, {'1':1},{'0':-1},{'0':True},{'0':1.5}])
def test_bad_totals_rejected(setup,totals):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    with pytest.raises(ValueError):apply(a,k,1,totals)
    assert c.spool('04112233')['remaining_mg']==500000

def test_no_full_plan_on_cancel(setup):
    c,a,f=setup;k=a.begin('a','j','s',['0'],'capture',f)
    with pytest.raises(ValueError):a.apply(k,1,{'0':10000},state='cancelled',source='capture',basis='completed_gcode')

def test_two_tools_overdraw_rolls_back_all(setup):
    c,a,f=setup;f={'a':snapshot('a',{'0':'04112233','1':'04AABBCC'})}
    k=a.begin('a','j','s',['0','1'],'capture',f)
    with pytest.raises(AccountingConflict):apply(a,k,1,{'0':1000,'1':400000})
    assert c.spool('04112233')['remaining_mg']==500000

def test_legacy_import_preserves_id_and_is_idempotent(tmp_path):
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c)
    original={'spools':{'old-id':{'name':'Black','material':'PLA','remaining_g':583.217,'color':'#000000'}},'runs':{},'language':'ru'}
    a.import_legacy_snapshot(original,{'old-id':'04112233'})
    assert c.spool('04112233')['spool_id']=='old-id'
    assert c.spool('04112233')['remaining_mg']==583217
    f={'a':snapshot('a',{'0':'04112233'})};k=a.begin('a','j','s',['0'],'capture',f);apply(a,k,1,{'0':1000})
    a.import_legacy_snapshot(original,{'old-id':'04112233'})
    assert c.spool('04112233')['remaining_mg']==582217
    assert original['spools']['old-id']['remaining_g']==583.217
    c.close()

def test_restart_duplicate_and_persistent_journal(tmp_path):
    path=tmp_path/'db';c=UidCatalog(path);a=UidAccounting(c);c.register('04112233','Red',500000)
    k=a.begin('a','j','s',['0'],'capture',{'a':snapshot('a',{'0':'04112233'})});c.close()
    def worker():
        local=UidCatalog(path);engine=UidAccounting(local)
        try:return apply(engine,k,1,{'0':10000},'cancelled')
        finally:local.close()
    # One writer owns SQLite; concurrent producers are covered through AccountingOwner.
    results=[worker(),worker()]
    assert sorted(results)==['applied','duplicate']
    c=UidCatalog(path);assert c.spool('04112233')['remaining_mg']==490000;c.close()

def test_reconnect_between_polls_is_not_missed(setup):
    c,a,f=setup
    f['a'].update(client_session='client1',generation=1,epoch='klipper1')
    k=a.begin('a','j','s',['0'],'capture',f)
    f['a']['generation']=2 # same UID, no offline snapshot reached the app
    a.observe(f)
    with pytest.raises(AccountingConflict):apply(a,k,1,{'0':1000})

def test_legacy_history_not_silently_imported_without_dedup(tmp_path):
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c)
    with pytest.raises(AccountingConflict):
        a.import_legacy_snapshot({'spools':{},'runs':{'old':{'status':'committed'}}},{})
    c.close()

def test_service_rejects_missed_start(setup):
    c,a,f=setup
    class Fleet:
        def snapshot(self):return f
    service=TrackerUidService(Fleet(),c)
    with pytest.raises(AccountingConflict):
        service.handle_event('a',dict(job_id='j',started_at='s',state='started',sequence=0,totals_mg={'0':100},source='capture',basis='executed_gcode'))
    assert c.spool('04112233')['remaining_mg']==500000

def test_terminal_without_recorded_start_cannot_use_current_spool(setup):
    c,a,f=setup
    with pytest.raises(AccountingConflict):apply(a,job_key('a','missing','s'),1,{'0':1000},'cancelled')
    assert c.spool('04112233')['remaining_mg']==500000
