import uuid
import pytest
from tracker_desktop_spoolman import change,configuration_revision,configure,status
from tracker_desktop_inventory import context
from test_uid_port_library import lib,remote
from test_uid_delivery import bench as delivery_bench,decision


def test_remote_attach_duplicate_and_guarded_detach_keep_ledger(lib):
    l,f=lib;r=remote(l)
    l.save_settings({'printers':[dict(id='a',name='A',url='http://127.0.0.1:19101')],'spoolman_url':r['url']},l.settings()['revision'])
    def request(action,data):
        with l.accounting.transaction():rev=context(l,f)['revision']
        return dict(action=action,data=data,expected_revision=rev,request_id=uuid.uuid4().hex,confirmed=True)
    req=request('attach',dict(id=42,slot=0,catalog_revision=r['revision']))
    saved=change(l,**req,fleet=f)
    assert change(l,**req,fleet=f)==saved and len(l.snapshot()['spools'])==1
    sid=saved['spool_id'];key=l.accounting.begin('a','job','1000',['0'],'test',f)
    with pytest.raises(ValueError,match='активном'):change(l,**request('detach',{'id':sid}),fleet=f)
    l.accounting.apply(key,1,{'0':750},state='completed',source='test',basis='motion_estimate')
    before=[tuple(r) for r in l.db.execute('SELECT * FROM uid_debits')]
    with pytest.raises(ValueError,match='операции'):change(l,**request('detach',{'id':sid}),fleet=f)
    with l.db:l.db.execute("UPDATE uid_remote_outbox SET state='sent'")
    before_spool=l.snapshot()['spools'][0]
    change(l,**request('detach',{'id':sid}),fleet=f)
    after=l.snapshot()['spools'][0]
    assert after['spool_id']==sid and after['remaining_mg']==before_spool['remaining_mg'] and after['remote'] is None
    assert l.db.execute('SELECT spool_id FROM manual_assignments').fetchone()[0]==sid
    assert [tuple(r) for r in l.db.execute('SELECT * FROM uid_debits')]==before
    assert l.accounting.apply(key,1,{'0':750},state='completed',source='test',basis='motion_estimate')=='duplicate'
    assert l.db.execute('SELECT url FROM uid_remote_outbox').fetchone()[0]==r['url']


def test_spoolman_configuration_revision_is_independent_but_detects_conflict(lib):
    l,f=lib;rev=configuration_revision(l.settings()['values'])
    l.save_settings({'language':'de'},l.settings()['revision'])
    configure(l,{'spoolman_url':'http://127.0.0.1:19101','spoolman_mode':'read'},rev)
    with pytest.raises(ValueError,match='изменились'):configure(l,{'spoolman_url':'http://127.0.0.1:19102','spoolman_mode':'send'},rev)


def test_read_and_off_modes_cannot_send_approved_operations(delivery_bench):
    owner,fake,sender,*_=delivery_bench
    decision(owner)
    for mode in ('read','off'):
        owner.call('save_settings',values={'spoolman_mode':mode},expected_revision=owner.call('settings')['revision'])
        assert sender.send_one()=='disabled' and not fake.writes
    owner.call('save_settings',values={'spoolman_mode':'send'},expected_revision=owner.call('settings')['revision'])
    assert sender.send_one()=='sent' and len(fake.writes)==1
