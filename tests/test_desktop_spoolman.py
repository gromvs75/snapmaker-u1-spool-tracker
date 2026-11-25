import uuid
from types import SimpleNamespace
import pytest
from tracker_desktop_spoolman import change,configuration_revision,configure,status
from tracker_desktop_inventory import context
from tracker_desktop_model import snapshot as desktop_snapshot
from tracker_uid_motion_lifecycle import MotionLifecycle
from test_uid_port_library import lib,remote
from test_uid_delivery import bench as delivery_bench,decision


@pytest.mark.parametrize('mode', ['read', 'send'])
def test_refreshed_weight_reaches_overview_and_forecast(lib, mode):
    l, fleet = lib
    url = 'http://127.0.0.1:18899'
    l.save_settings(dict(printers=[dict(id='a', name='A', url='http://127.0.0.1:19101')],
                         spoolman_url=url, spoolman_mode=mode), l.settings()['revision'])
    item = dict(id=12, name='Yellow PETG', material='PETG', color='#d8ff71', archived=False)
    def refresh(weight):
        return l.cache_catalog(url, {'12': dict(item, remaining_g=weight)})

    old = refresh(872.3)
    linked = change(l, 'attach', dict(id=12, slot=3, catalog_revision=old['revision']),
                    context_revision(l, fleet), 'attach-yellow', True, fleet=fleet)
    sid = linked['spool_id']
    local = l.create('Local PETG', 385.7, fleet=fleet)['spool_id']
    history = SimpleNamespace(unaccounted_history=lambda pid: [])
    MotionLifecycle(SimpleNamespace(db=l.db))
    refresh(694)
    overview = desktop_snapshot(l, history, fleet)
    assert overview['spools'][sid]['remaining_g'] == 694
    assert overview['spools'][local]['remaining_g'] == 385.7
    assert l.forecast_inventory(fleet=fleet)['printers']['a']['heads'][3]['spool']['remaining_mg'] == 694000
    assert not l.snapshot()['remote_outbox']


def test_catalog_refresh_preserves_active_and_unsettled_accounting(lib):
    l, fleet = lib
    remote_spool = remote(l)
    url = remote_spool['url']
    l.save_settings(dict(spoolman_url=url, spoolman_mode='send'), l.settings()['revision'])
    sid = l.create('Remote PLA', 0, fleet=fleet, remote=remote_spool,
                   assignment=dict(printer_id='a', channel='0', expected_version='', confirmed=True))['spool_id']
    item = dict(l.remote_catalog(url)['items'][0], remaining_g=100)
    baseline = l.catalog_refresh_context(url)
    key = l.accounting.begin('a', 'job', '1000', ['0'], 'test', fleet)
    l.cache_catalog(url, {'42': item}, refresh_context=baseline)
    assert l.snapshot()['spools'][0]['remaining_mg'] == 123456

    l.accounting.apply(key, 1, {'0': 3456}, state='completed', source='test', basis='motion_estimate')
    before_delivery = l.catalog_refresh_context(url)
    l.cache_catalog(url, {'42': item}, refresh_context=before_delivery)
    assert l.snapshot()['spools'][0]['remaining_mg'] == 120000
    before_delivery = l.catalog_refresh_context(url)
    with l.db:
        l.db.execute("UPDATE uid_remote_outbox SET state='sent' WHERE spool_id=?", (sid,))
    l.cache_catalog(url, {'42': item}, refresh_context=before_delivery)
    assert l.snapshot()['spools'][0]['remaining_mg'] == 120000

    fresh = l.catalog_refresh_context(url)
    l.cache_catalog(url, {'42': item}, refresh_context=fresh)
    assert l.snapshot()['spools'][0]['remaining_mg'] == 100000
    l.cache_catalog(url, {'42': dict(item, remaining_g=500)}, refresh_context=fresh)
    assert l.remote_catalog(url)['items'][0]['remaining_g'] == 100
    assert l.snapshot()['spools'][0]['remaining_mg'] == 100000
    l.cache_catalog(url, None)
    assert l.snapshot()['spools'][0]['remaining_mg'] == 100000
    assert [r['delta_mg'] for r in l.db.execute('SELECT delta_mg FROM uid_debits')] == [3456]


def context_revision(library, fleet):
    with library.accounting.transaction():
        return context(library, fleet)['revision']


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
