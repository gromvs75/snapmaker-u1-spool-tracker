import pytest
from test_desktop_inventory import inventory,perform,slots
from tracker_uid_motion_lifecycle import MotionLifecycle
from types import SimpleNamespace
from test_uid_forecast import entry
from tracker_uid_forecast import forecast_entry


def test_offline_saved_assignment_forecasts_without_authorizing_accounting(inventory):
    l,d,f=inventory
    MotionLifecycle(SimpleNamespace(db=l.db))
    sid=l.create('Saved PLA',571.597,fleet=f)['spool_id']
    perform(l,d,f,'slots',slots(sid))
    before=l.snapshot()['spools']
    h=l.forecast_inventory(fleet={})['printers']['a']['heads']
    assert not h[0]['usable'] and h[0]['forecast_usable']
    r=forecast_entry(entry([4.01,0,0,0]),h,10)
    assert r['status']=='ok' and r['provisional']
    assert r['rows'][0]['after']==pytest.approx(567.587)
    assert l.snapshot()['spools']==before
    assert not l.catalog.inventory_snapshot('a',{})['slots']['1']
    assert l.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0
    assert l.db.execute('SELECT count(*) FROM uid_jobs').fetchone()[0]==0
    perform(l,d,f,'spools/update',dict(id=sid,remaining_g='13'))
    h=l.forecast_inventory(fleet={})['printers']['a']['heads']
    assert forecast_entry(entry([4.01,0,0,0]),h,10)['status']=='shortage'


def test_conflicting_uid_does_not_become_provisional_forecast(inventory):
    l,d,f=inventory
    MotionLifecycle(SimpleNamespace(db=l.db))
    l.catalog.register('04112233','UID',500000)
    for p in f:f[p]['channels']['0']=dict(state='present',uid='04112233')
    for printer in l.forecast_inventory(fleet=f)['printers'].values():
        h=printer['heads'];assert not h[0]['forecast_usable']
        assert forecast_entry(entry([4,0,0,0]),h,10)['status']=='unknown'


from test_legacy_backup_restore import old_backup,restore
from tracker_uid_session import Session


def test_import_forecast_keeps_uncertain_spoolman_balance_blocked(tmp_path,old_backup):
    s=Session(tmp_path/'forecast-import',allowed_urls=[])
    try:
        restore(s,old_backup)
        inventory=s.call('forecast_inventory')
        heads=next(p['heads'] for p in inventory['printers'].values() if p['heads'][0]['spool'])
        assert heads[0]['forecast_usable'] and not heads[0]['usable']
        assert not heads[1]['forecast_usable'] and not heads[1]['usable']
        assert forecast_entry(entry([0,4,0,0]),heads,10)['status']=='unknown'
        assert s.call('settings')['values']['spoolman_mode']=='off'
    finally:s.close()
