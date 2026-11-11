import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from tracker_uid_client import PrinterEndpoint, UidClient, UidFleet, validate_status
from tracker_uid_catalog import UidCatalog


def status(epoch='first',seq=1):
    return dict(schema_version=1,epoch=epoch,sequence=seq,state='ready',channels={str(i):dict(state='present',uid='04112233',age_seconds=0.,sequence=seq) if i==0 else dict(state='unknown',uid=None) for i in range(4)})

def client():return UidClient(PrinterEndpoint('a','U1_1','http://localhost:1'),max_observation_age=2)

@pytest.mark.parametrize('value',[None,{},dict(schema_version=2),dict(schema_version=True)])
def test_schema_rejected(value):
    with pytest.raises(ValueError):validate_status(value)

@pytest.mark.parametrize('uid',['00000000','08112233','123','not-a-uid',None])
def test_invalid_uid(uid):
    s=status();s['channels']['0']['uid']=uid
    with pytest.raises(ValueError):validate_status(s)

def test_out_of_order_and_new_epoch():
    c=client();c._accept(status(seq=9))
    with pytest.raises(ValueError):c._accept(status(seq=8))
    c._accept(status(epoch='second',seq=1))
    assert c.snapshot()['epoch']=='second'

def test_offline_and_local_staleness():
    c=client();c._accept(status());c._received-=3
    assert c.snapshot()['channels']['0']['state']=='stale'
    c._invalidate('offline')
    assert c.snapshot()['channels']['0']['uid'] is None

def test_snapshot_is_copy():
    c=client();c._accept(status());s=c.snapshot();s['channels']['0']['uid']='changed'
    assert c.snapshot()['channels']['0']['uid']=='04112233'

def test_partial_snapshot_not_accepted():
    s=status();del s['channels']['3']
    with pytest.raises(ValueError):validate_status(s)

def test_duplicate_printers_rejected():
    with pytest.raises(ValueError):UidFleet([PrinterEndpoint('a','A','http://localhost:1')]*2)
    with pytest.raises(ValueError):UidFleet([PrinterEndpoint('a','A','http://localhost:1'),PrinterEndpoint('b','B','http://localhost:1')])

def snap(pid,uid=None,state='ready',channel='0'):
    return dict(printer_id=pid,state=state,channels={str(i):dict(state='present' if str(i)==channel and uid else 'absent',uid=uid if str(i)==channel else None) for i in range(4)})

def test_transfer_balance_conflict_and_restart(tmp_path):
    path=tmp_path/'catalog.sqlite';cat=UidCatalog(path)
    spool=cat.register('04112233','Red',500000)
    assert cat.register('04112233','Red',1000000)==spool
    a=snap('a','04112233');b=snap('b')
    assert cat.reconcile({'a':a,'b':b})[0]['usable']
    b=snap('b','04112233',channel='2')
    assert all(r['state']=='conflict' for r in cat.reconcile({'a':a,'b':b}))
    a=snap('a',state='offline')
    assert all(not r['usable'] for r in cat.reconcile({'a':a,'b':b}))
    a=snap('a');rows=cat.reconcile({'a':a,'b':b})
    assert len(rows)==1 and rows[0]['printer_id']=='b' and rows[0]['channel']=='2'
    assert rows[0]['spool']==spool
    cat.close();cat=UidCatalog(path)
    assert cat.reconcile({})[0]['state']=='uncertain'
    assert cat.spool('04112233')==spool
    cat.close()

def test_unknown_needs_registration(tmp_path):
    cat=UidCatalog(tmp_path/'db')
    row=cat.reconcile({'a':snap('a','04112233')})[0]
    assert row['state']=='needs_registration' and row['spool'] is None
    cat.close()

@pytest.mark.parametrize('age',[float('nan'),float('inf'),-1,True,'0'])
def test_invalid_observation_age(age):
    s=status();s['channels']['0']['age_seconds']=age
    with pytest.raises(ValueError):validate_status(s)

def test_key_not_in_endpoint_repr():
    assert 'secret' not in repr(PrinterEndpoint('a','A','https://localhost','secret'))

def test_wrong_module_state_never_exposes_uid():
    c=client();s=status();s['state']='unavailable';c._accept(s)
    assert c.snapshot()['state']=='module_unavailable'
    assert c.snapshot()['channels']['0']['uid'] is None

def test_lost_heartbeat_invalidates_snapshot():
    c=client();c._accept(status());c._received-=10
    assert c.snapshot()['state']=='offline'
    assert c.snapshot()['channels']['0']['uid'] is None
