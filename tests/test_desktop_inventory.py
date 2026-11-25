import copy
import uuid

import pytest

from tracker_desktop_inventory import DesktopInventory,context
from tracker_uid_accounting import UidAccounting
from tracker_uid_catalog import UidCatalog
from tracker_uid_library import Library
from test_uid_accounting import snapshot


@pytest.fixture
def inventory(tmp_path):
    c=UidCatalog(tmp_path/'inventory.sqlite');l=Library(UidAccounting(c))
    l.save_settings({'printers':[dict(id=p,name='Printer '+p,url='http://127.0.0.1:'+str(19000+i)) for i,p in enumerate(('a','b'))]},l.settings()['revision'])
    f={p:snapshot(p,{}) for p in ('a','b')}
    yield l,DesktopInventory(l),f
    c.close()


def intent(l,f,action,data):
    with l.accounting.transaction():rev=context(l,f)['revision']
    return dict(action=action,data=data,expected_revision=rev,request_id=uuid.uuid4().hex,confirmed=True)


def perform(l,d,f,action,data):return d.execute(**intent(l,f,action,data),fleet=f)
def slots(*spools):return {str(i+1):spools[i] if i<len(spools) else '' for i in range(4)}
def spool(l,sid):return next(s for s in l.snapshot()['spools'] if s['spool_id']==sid)


def test_create_lost_response_same_intent_and_changed_replay(inventory):
    l,d,f=inventory
    request=intent(l,f,'spools/add',dict(name='PLA',material='PLA',remaining_g='125.26',color='#123456',assign_slot='1',expected_slot=''))
    result=d.execute(**request,fleet=f)
    assert d.execute(**request,fleet=f)['status']=='duplicate'
    assert len(l.snapshot()['spools'])==1
    assert spool(l,result['spool_id'])['remaining_mg']==125260
    changed=copy.deepcopy(request);changed['data']['remaining_g']='250'
    with pytest.raises(ValueError,match='Повтор'):d.execute(**changed,fleet=f)
    assert l.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0


def test_exact_weight_color_clear_stale_and_remote_guards(inventory):
    l,d,f=inventory
    sid=l.create('PLA',100,fleet=f)['spool_id']
    edit=intent(l,f,'spools/update',dict(id=sid,remaining_g='125.259'))
    d.execute(**edit,fleet=f);assert spool(l,sid)['remaining_mg']==125259
    assert d.execute(**edit,fleet=f)['status']=='duplicate'
    for color in ('#aabbcc',None,''):
        perform(l,d,f,'spools/color',dict(id=sid,color=color))
        assert spool(l,sid)['details']['color']==color
    stale=intent(l,f,'spools/update',dict(id=sid,remaining_g='1'))
    l.create('Other',2,fleet=f)
    with pytest.raises(ValueError,match='изменились'):d.execute(**stale,fleet=f)
    with l.db:l.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(sid,'http://127.0.0.1:18899',1))
    for action,data in [('spools/update',dict(id=sid,remaining_g='1')),('spools/color',dict(id=sid,color=None)),('spools/delete',dict(id=sid))]:
        with pytest.raises(ValueError,match='Spoolman'):perform(l,d,f,action,data)
    assert spool(l,sid)['remaining_mg']==125259


@pytest.mark.parametrize('fault',['offline','tag','duplicate','missing','other_printer','active','generation','sql'])
def test_bulk_assignment_rollback_preserves_all_four_heads(inventory,fault):
    l,d,f=inventory
    a=l.create('A',100,fleet=f)['spool_id'];b=l.create('B',100,fleet=f)['spool_id']
    perform(l,d,f,'slots',slots(a,b))
    data=slots(b,a)
    if fault=='offline':f['a']['state']='offline'
    if fault=='tag':f['a']=snapshot('a',{'1':'04112233'})
    if fault=='duplicate':data=slots(b,b)
    if fault=='missing':data=slots(b,'missing')
    if fault=='other_printer':
        c=l.create('C',100,fleet=f,assignment=dict(printer_id='b',channel='0',expected_version='',confirmed=True))
        data=slots(b,c['spool_id'])
    if fault=='active':l.accounting.begin('a','job','1000',['0'],'test',f)
    request=intent(l,f,'slots',data)
    if fault=='generation':f['a']['generation']=2
    if fault=='sql':l.db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON manual_assignments WHEN NEW.channel='1' BEGIN SELECT RAISE(ABORT,'test'); END")
    before=[tuple(r) for r in l.db.execute('SELECT * FROM manual_assignments')]
    with pytest.raises(Exception):d.execute(**request,fleet=f)
    assert [tuple(r) for r in l.db.execute('SELECT * FROM manual_assignments')]==before
    assert l.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==0


def test_atomic_swap_reconnect_confirm_and_other_printer_preserved(inventory):
    l,d,f=inventory
    a=l.create('A',100,fleet=f)['spool_id'];b=l.create('B',100,fleet=f)['spool_id']
    c=l.create('C',100,fleet=f,assignment=dict(printer_id='b',channel='0',expected_version='',confirmed=True))
    perform(l,d,f,'slots',slots(a,b));perform(l,d,f,'slots',slots(b,a))
    assert l.db.execute("SELECT spool_id FROM manual_assignments WHERE printer_id='a' AND channel='0'").fetchone()[0]==b
    f['a']['generation']=2
    perform(l,d,f,'slots',slots(b,a))
    assert all(r[0]==1 for r in l.db.execute('SELECT confirmed FROM manual_assignments'))
    perform(l,d,f,'slots',slots())
    assert l.db.execute('SELECT spool_id FROM manual_assignments').fetchone()[0]==c['spool_id']


def test_confirm_positions_after_uid_module_removal_restores_forecast(inventory):
    from types import SimpleNamespace
    from tracker_uid_forecast import forecast_entry
    from tracker_uid_motion_lifecycle import MotionLifecycle

    l, d, fleet = inventory
    MotionLifecycle(SimpleNamespace(db=l.db))
    spools = [l.create('PLA ' + str(i), grams, fleet=fleet, details=dict(color=color, material='PLA'))['spool_id']
              for i, (grams, color) in enumerate([(392.9, '#151A1C'), (189.5, '#FFFFFF'),
                                                (833.6, '#FF7F26'), (831.9, '#299467')])]
    perform(l, d, fleet, 'slots', slots(*spools))
    original_tagged = l.catalog.register('04112233', 'Original RFID spool', 800000)
    l.catalog.reconcile({'a':snapshot('a', {'0':'04112233', '1':'04AABBCC'}),
                         'b':snapshot('b', {'2':'04AABBCA'})})
    fleet['a'].update(state='module_missing', printer_connected=True, print_state='standby',
                      channels={str(i):dict(state='unknown', uid=None) for i in range(4)})
    fleet['b'] = snapshot('b', {'2':'04AABBCA'})
    plan = dict(weights=[8.28, 0, 0, 0], colors=['#000000'], filament_types=['PLA'], plate=1)
    def preview():
        heads = l.forecast_inventory(fleet=fleet)['printers']['a']['heads']
        return forecast_entry(plan, heads, reserve=5)

    assert preview()['status'] == 'unknown'
    before = {r['spool_id']:r['remaining_mg'] for r in l.snapshot()['spools']}
    with pytest.raises(ValueError, match='Unresolved UID'):
        perform(l, d, fleet, 'slots', slots(original_tagged['spool_id'], *spools[1:]))
    assert preview()['status'] == 'unknown'
    perform(l, d, fleet, 'slots', slots(*spools))
    result = preview()
    assert result['status'] == 'ok'
    assert [(r['channel'], r['after']) for r in result['rows']] == [('0', pytest.approx(384.62))]
    assert {r['spool_id']:r['remaining_mg'] for r in l.snapshot()['spools']} == before
    assert l.catalog.spool('04112233') == original_tagged
    assert [tuple(r) for r in l.db.execute('SELECT printer_id,channel FROM uid_locations')] == [('b', '2')]
    assert l.db.execute('SELECT COUNT(*) FROM uid_debits').fetchone()[0] == 0
    assert l.catalog.inventory_snapshot('a', fleet)['slots']['1'] == spools[0]

    # A reader that comes back can establish a new conflict.
    fleet['a'] = snapshot('a', {'0':'04112233'})
    assert preview()['status'] == 'unknown'
    assert l.catalog.inventory_snapshot('a', fleet)['slots']['1'] != spools[0]


@pytest.mark.parametrize('state,connected,printing', [
    ('stopped', False, False),
    ('module_unavailable', True, False),
    ('module_missing', False, False),
    ('module_missing', True, True),
    ('ready', True, False),
])
def test_manual_confirmation_cannot_discard_uid_without_idle_stock_connection(inventory, state, connected, printing):
    l, d, fleet = inventory
    sid = l.create('Manual PLA', 392.9, fleet=fleet)['spool_id']
    perform(l, d, fleet, 'slots', slots(sid))
    present = snapshot('a', {'0':'04112233'})
    l.catalog.reconcile({'a':present})
    fleet['a'] = dict(present, state=state, printer_connected=connected,
                      print_state='printing' if printing else 'standby')
    if state != 'ready':
        fleet['a']['channels'] = {str(i):dict(state='unknown', uid=None) for i in range(4)}
    with pytest.raises(ValueError):
        perform(l, d, fleet, 'slots', slots(sid))
    assert l.db.execute("SELECT COUNT(*) FROM uid_locations WHERE printer_id='a'").fetchone()[0] == 1
    assert l.db.execute('SELECT COUNT(*) FROM uid_debits').fetchone()[0] == 0


def test_delete_only_unused_and_no_active_weight_rewrite(inventory):
    l,d,f=inventory
    unused=perform(l,d,f,'spools/add',dict(name='Unused',remaining_g='1'))['spool_id']
    perform(l,d,f,'spools/delete',dict(id=unused))
    a=l.create('Used',100,fleet=f)['spool_id'];perform(l,d,f,'slots',slots(a))
    key=l.accounting.begin('a','job','1000',['0'],'test',f)
    with pytest.raises(ValueError):perform(l,d,f,'spools/update',dict(id=a,remaining_g='200'))
    l.accounting.apply(key,1,{'0':750},state='completed',source='test',basis='motion_estimate')
    perform(l,d,f,'slots',slots())
    with pytest.raises(ValueError,match='истории'):perform(l,d,f,'spools/delete',dict(id=a))
    perform(l,d,f,'spools/update',dict(id=a,remaining_g='98.777'))
    assert spool(l,a)['remaining_mg']==98777
    assert l.accounting.apply(key,1,{'0':750},state='completed',source='test',basis='motion_estimate')=='duplicate'
    assert spool(l,a)['remaining_mg']==98777
