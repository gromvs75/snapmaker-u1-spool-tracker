import copy
import pytest
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting
from tracker_uid_library import Library, search_items
from tracker_uid_spoolman import catalog_item
from test_uid_accounting import snapshot

@pytest.fixture
def lib(tmp_path):
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c);lib=Library(a)
    yield lib,{'a':snapshot('a',{}),'b':snapshot('b',{})}
    c.close()

def assignment(channel='0',version='',printer='a'):
    return dict(printer_id=printer,channel=channel,expected_version=version,confirmed=True)

def remote(lib, name='PLA'):
    item=catalog_item({'id':42,'filament':{'name':name,'vendor':{'name':'Maker'},'material':'PLA'},'remaining_weight':123.456})
    cache=lib.cache_catalog('http://127.0.0.1:18899',{'42':item})
    return dict(url='http://127.0.0.1:18899',id=42,revision=cache['revision'])

@pytest.mark.parametrize('fault',['stale','unchecked','offline','tag','active_other_head','sql'])
def test_atomic_create_failure_leaves_no_orphan(lib,fault):
    l,f=lib;opts=assignment()
    if fault=='stale':opts['expected_version']='stale'
    if fault=='unchecked':opts['confirmed']=False
    if fault=='offline':f['a']['state']='offline'
    if fault=='tag':f['a']=snapshot('a',{'0':'04112233'})
    if fault=='active_other_head':
        l.create('Other',10,fleet=f,assignment=assignment('3'))
        l.accounting.begin('a','job','1000',['3'],'test',f)
    if fault=='sql':l.db.execute("CREATE TRIGGER fail_assign BEFORE INSERT ON manual_assignments BEGIN SELECT RAISE(ABORT,'test'); END")
    before=l.snapshot()
    with pytest.raises(Exception):l.create('New',123.456,fleet=f,assignment=opts)
    assert l.snapshot()==before


def test_create_assign_replace_detach_and_two_printers(lib):
    l,f=lib;s=l.create('Same',100,fleet=f,assignment=assignment())
    t=l.create('Same',10,fleet=f,assignment=assignment(printer='b'))
    new=l.create('Replacement',20,fleet=f,assignment=assignment(version=s['version']))
    assert len(l.snapshot()['spools'])==3
    assert l.db.execute("SELECT spool_id FROM manual_assignments WHERE printer_id='b'").fetchone()[0]==t['spool_id']
    with pytest.raises(ValueError):l.detach('a','0',s['version'],True,fleet=f)
    l.detach('a','0',new['version'],True,fleet=f)
    assert l.db.execute('SELECT count(*) FROM manual_assignments').fetchone()[0]==1


def test_search_name_and_manufacturer_no_duplicate():
    item=catalog_item({'id':42,'filament':{'name':'MAKER PLA','vendor':{'name':'Maker'},'material':'PLA'},'remaining_weight':1})
    assert item['name']=='MAKER PLA'
    assert search_items([item],'maker 42 pla')==[item]
    assert search_items([item],'')==[item]
    assert search_items([item],'petg')==[]
    assert catalog_item({'id':1,'filament':{'name':None,'vendor':None}})['name']=='Spool'


def test_name_only_preserves_active_job_balance_identity_and_outbox(lib):
    l,f=lib;r=remote(l);s=l.create('ignored',0,fleet=f,remote=r,assignment=assignment())
    key=l.accounting.begin('a','job','1000',['0'],'test',f)
    l.accounting.apply(key,1,{'0':1234},state='active',source='test',basis='motion_estimate')
    tables=['uid_remote_links','uid_remote_outbox','uid_debits','uid_jobs','uid_job_tools','manual_assignments']
    before={t:[tuple(row) for row in l.db.execute('SELECT * FROM '+t)] for t in tables}
    old=l.compare_name(s['spool_id']);assert old['different'] is False
    remote(l,'New PLA');comparison=l.compare_name(s['spool_id'])
    with pytest.raises(ValueError):l.rename_from_remote(s['spool_id'],old['revision'],True)
    l.rename_from_remote(s['spool_id'],comparison['revision'],True)
    assert l.snapshot()['spools'][0]['name']=='Maker New PLA'
    assert l.snapshot()['spools'][0]['remaining_mg']==122222
    assert before=={t:[tuple(row) for row in l.db.execute('SELECT * FROM '+t)] for t in tables}
    assert l.accounting.apply(key,1,{'0':1234},state='active',source='test',basis='motion_estimate')=='duplicate'
    assert len(l.snapshot()['remote_outbox'])==1
    l.cache_catalog(r['url'],None)
    with pytest.raises(ValueError):l.rename_from_remote(s['spool_id'],comparison['revision'],True)


def test_same_name_never_merges_local_with_remote(lib):
    l,f=lib;r=remote(l)
    l.create('Maker PLA',10,fleet=f)
    l.create('Maker PLA',10,fleet=f,remote=r)
    assert len(l.snapshot()['spools'])==2
    with pytest.raises(ValueError):l.create('Maker PLA',10,fleet=f,remote=r)


def test_preferences_revision_and_reopen(lib):
    l,_=lib;old=l.settings()
    l.save_settings({'printer_names':{'a':'Bench A'},'spoolman_url':'http://127.0.0.1:18899/'},old['revision'])
    assert l.settings()['values']['spoolman_url']=='http://127.0.0.1:18899'
    with pytest.raises(ValueError):l.save_settings({},old['revision'])
