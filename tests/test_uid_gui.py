import pytest
from test_uid_manual import manual, assign, begin
from tracker_uid_accounting import AccountingConflict

def transfer(a,f,version,**kw):
    data=dict(spool_id='manual-id',source_printer='a',source_channel='0',target_printer='b',target_channel='1',
              expected_version=version,request_id='transfer-1',confirmed=True)
    data.update(kw)
    return a.transfer_manual(**data,fleet=f)

def test_atomic_transfer_idempotent_and_balance_unchanged(manual):
    c,a,f=manual;old=assign(a,f)
    result=transfer(a,f,old['version'])
    assert transfer(a,f,old['version'])==result
    rows=c.db.execute('SELECT * FROM manual_assignments').fetchall()
    assert len(rows)==1 and rows[0]['printer_id']=='b' and rows[0]['channel']=='1'
    assert c.db.execute('SELECT remaining_mg FROM uid_spools').fetchone()[0]==500000
    assert c.db.execute('SELECT count(*) FROM manual_transfers').fetchone()[0]==1
    with pytest.raises(AccountingConflict):transfer(a,f,old['version'],target_channel='2')

@pytest.mark.parametrize('fault',['occupied','active','offline','stale','target_tag','source_tag','unchecked'])
def test_failed_transfer_keeps_source(manual,fault):
    c,a,f=manual;old=assign(a,f)
    if fault=='occupied':
        c.register_manual('Other',100,spool_id='other');assign(a,f,'b','1','other')
    if fault=='active':begin(a,f)
    if fault=='offline':f['b']['state']='offline'
    if fault=='stale':old['version']='stale'
    if fault=='target_tag':f['b']['channels']['1']={'state':'present','uid':'04112233'}
    if fault=='source_tag':f['a']['channels']['0']={'state':'present','uid':'04112233'}
    with pytest.raises(ValueError):transfer(a,f,old['version'],confirmed=fault!='unchecked')
    assert c.db.execute("SELECT printer_id FROM manual_assignments WHERE spool_id='manual-id'").fetchone()[0]=='a'
    assert c.db.execute('SELECT count(*) FROM manual_transfers').fetchone()[0]==0


def test_confirmation_stale_version_and_occupied_slot(manual):
    c,a,f=manual;old=assign(a,f)
    with pytest.raises(AccountingConflict):a.assign_manual('a','0','manual-id',f,confirmed=True,expected_version='')
    newer=a.assign_manual('a','0','manual-id',f,confirmed=True,expected_version=old['version'])
    with pytest.raises(AccountingConflict):a.assign_manual('a','0','manual-id',f,confirmed=True,expected_version=old['version'])
    assert c.db.execute('SELECT version FROM manual_assignments').fetchone()[0]==newer['version']


def test_transfer_sql_failure_rolls_back_source(manual):
    import sqlite3
    c,a,f=manual;old=assign(a,f)
    c.db.execute("CREATE TRIGGER fail_transfer BEFORE INSERT ON manual_transfers BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):transfer(a,f,old['version'])
    row=c.db.execute('SELECT * FROM manual_assignments').fetchone()
    assert row['printer_id']=='a' and row['version']==old['version']


@pytest.mark.parametrize('printing_printer',['a','b'])
def test_transfer_blocked_when_other_head_prints(manual,printing_printer):
    c,a,f=manual;old=assign(a,f)
    c.register_manual('Printing',100000,spool_id='printing')
    assign(a,f,printing_printer,'3','printing')
    begin(a,f,printing_printer,'3','other-head')
    with pytest.raises(AccountingConflict,match='Печать активна'):
        transfer(a,f,old['version'])
    assert c.db.execute("SELECT printer_id FROM manual_assignments WHERE spool_id='manual-id'").fetchone()[0]=='a'
    assert c.db.execute('SELECT count(*) FROM manual_transfers').fetchone()[0]==0
