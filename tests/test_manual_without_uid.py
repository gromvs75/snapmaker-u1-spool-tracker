"""Manual identity works without an RFID extra, without granting UID authority."""
import copy
import time
import pytest
from test_uid_accounting import snapshot
from test_uid_manual import manual, assign, begin, debit
from tracker_uid_accounting import AccountingConflict
from tracker_uid_client import UidClient, PrinterEndpoint
from tracker_printer_capabilities import manual_available


def stock(snapshot, state='standby'):
    snapshot.update(state='module_missing', printer_connected=True, print_state=state)
    return snapshot


def test_stock_assignment_confirmation_never_changes_balance(manual):
    c,a,f=manual
    for s in f.values(): stock(s)
    result=assign(a,f)
    assert result['identity_mode']=='manual'
    assert c.inventory_snapshot('a',f)['slots']['1']=='manual-id'
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    key=begin(a,f);a.observe(f)
    assert debit(a,key)=='applied'
    assert debit(a,key)=='duplicate'
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==499000


@pytest.mark.parametrize('fault',['disconnected','printing','paused','invalid_uid'])
def test_stock_assignment_rejects_unsafe_state(manual,fault):
    c,a,f=manual;stock(f['a']);assign(a,f)
    if fault=='disconnected': f['a']['printer_connected']=False
    if fault in ('printing','paused'):f['a']['print_state']=fault
    if fault=='invalid_uid':f['a']['state']='invalid_data'
    with pytest.raises(AccountingConflict):assign(a,f)


def test_stock_gap_cannot_be_laundered_by_reconfirmation(manual):
    c,a,f=manual;stock(f['a']);assign(a,f);key=begin(a,f)
    f['a']['printer_connected']=False;a.observe(f)
    f['a']['printer_connected']=True;f['a']['generation']=2;a.observe(f)
    with pytest.raises(AccountingConflict):debit(a,key)
    with pytest.raises(AccountingConflict):assign(a,f)
    assert a.job(key)['mapping_valid']==0


def test_stock_transfer_preserves_identity_and_request_dedup(manual):
    c,a,f=manual
    for s in f.values():stock(s)
    version=assign(a,f)['version']
    args=('manual-id','a','0','b','2',version,'stock-transfer',f)
    result=a.transfer_manual(*args,confirmed=True)
    assert a.transfer_manual(*args,confirmed=True)==result
    assert c.inventory_snapshot('b',f)['slots']['3']=='manual-id'
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000


def test_tagged_spool_can_be_manual_only_without_competing_uid_claim(manual):
    c,a,f=manual;stock(f['a'])
    sid=c.register('04112233','Tagged',100000)['spool_id']
    a.assign_manual('a','0',sid,f,confirmed=True)
    assert c.inventory_snapshot('a',f)['slots']['1']==sid
    assert c.spool('04112233')['remaining_mg']==100000
    f['b']['channels']['2']=dict(state='present',uid='04112233')
    a.observe(f)
    assert not any(r['usable'] for r in a.observe(f) if r.get('spool',{}).get('spool_id')==sid)
    with pytest.raises(AccountingConflict):a.assign_manual('a','0',sid,f,confirmed=True)


def test_printer_heartbeat_expires_independently_of_missing_module():
    client=UidClient(PrinterEndpoint('a','A','http://localhost:1'))
    client._accept_printer({'webhooks':{'state':'ready'},'print_stats':{'state':'standby'}})
    client._state='module_missing'
    assert manual_available(client.snapshot()) and client.snapshot()['state']!='ready'
    client._printer_received-=20
    assert not manual_available(client.snapshot())
    assert client.snapshot()['state']=='offline'


def test_stock_detach_changes_assignment_not_usage(manual):
    from tracker_uid_library import Library
    c,a,f=manual;stock(f['a']);version=assign(a,f)['version']
    result=Library(a).detach('a','0',version,True,fleet=f)
    assert result['status']=='detached'
    assert c.inventory_snapshot('a',f)['slots']['1']==''
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_stock_next_job_after_reconnect_and_conflicting_tag(manual):
    c, a, fleet = manual
    stock(fleet['a'])
    placement = assign(a, fleet)
    fleet['a']['printer_connected'] = False
    assert not c.inventory_snapshot('a', fleet)['slots']['1']
    stock(fleet['a'])
    fleet['a']['generation'] = 2
    assert c.inventory_snapshot('a', fleet)['slots']['1'] == 'manual-id'
    assert c.db.execute('SELECT version FROM manual_assignments').fetchone()[0] == placement['version']
    key = begin(a, fleet)
    assert debit(a, key) == 'applied'
    assert debit(a, key) == 'duplicate'
    fleet['a'] = snapshot('a', {'0': '04112233'})
    a.observe(fleet)
    fleet['a'] = snapshot('a', {})
    a.observe(fleet)
    stock(fleet['a'])
    assert not c.inventory_snapshot('a', fleet)['slots']['1']
