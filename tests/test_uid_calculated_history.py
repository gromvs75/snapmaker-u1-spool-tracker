import copy,json
import time
import pytest
from test_uid_motion_adapter import bench,history
from test_uid_accounting import snapshot
from tracker_uid_motion_lifecycle import MotionLifecycle


def test_next_slice_uses_the_unbooked_plan_of_the_same_spool(bench):
    from tracker_desktop_model import current_print_forecast
    from tracker_uid_forecast import forecast_entry

    _, catalog, fleet, adapter = bench
    fleet.states = {'a': snapshot('a', {'3': '04112233', '1': '04AABBCC'})}
    life = MotionLifecycle(adapter)
    accounting = adapter.service.accounting
    start = catalog.inventory_snapshot('a', fleet.states)
    key = life.start('a', filename='job.gcode', observed_at=1011, capture_id='forecast',
                     epoch='original', start=start, channels=['1', '3'])['job_key']
    order = [3, 1, 2, 0]
    current = history()
    task = dict(extruder_map_table=order, extruders_replenished=[0, 1, 2, 3], auto_replenish_filament=False)
    status = dict(print_stats=dict(state='printing', filename='job.gcode'), print_task_config=task)
    monitor = dict(status['print_stats'], checked_at=time.time(), connected=True)
    life.recovery_profile('a', current, dict(
        filename='job.gcode', started_at=1010.0, file_sha256='a' * 64, mapping=order,
        replenished=[0, 1, 2, 3], logical_weights=[20, 0, 0, 0], auto_replenish=False,
    ))
    upcoming = dict(weights=[485, 5, 0, 0], colors=['#fd8008', '#ffffff'], filament_types=['PLA', 'PLA'])

    def current_cards():
        spool = catalog.spool('04112233')
        sid = spool['spool_id']
        return current_print_forecast(dict(
            monitor=monitor, selected_printer='a', slots={'4': sid},
            slot_status={'4': 'recognized'}, safety_margin_g=5,
            spools={sid: dict(remaining_g=spool['remaining_mg'] / 1000)},
        ), life)

    def forecast():
        heads = []
        for channel, uid, color in [('3', '04112233', '#fd8008'), ('1', '04AABBCC', '#ffffff')]:
            spool = dict(catalog.spool(uid), details=dict(color=color, material='PLA'))
            heads.append(dict(channel=channel, spool=spool, usable=True))
        pending = life.pending_print_usage('a', monitor, heads)
        for head in heads:
            head['active_print_mg'] = None if pending is None else pending.get(head['spool']['spool_id'], 0)
        return forecast_entry(upcoming, heads, reserve=5)

    monitor['state'] = 'complete'
    life.replacement_observe('a', history('completed', ident='older'),
                             dict(status, print_stats=dict(state='complete', filename='job.gcode')))
    assert forecast()['status'] == 'ok'
    monitor['state'] = 'printing'
    assert forecast()['active_print_unknown']
    assert current_cards() == []
    life.replacement_observe('a', current, status)
    assert [(r['tool'], r['used'], r['after'], r['enough']) for r in current_cards()] == [('T3', 20, 480, True)]
    projected = forecast()
    assert projected['status'] == 'shortage' and projected['includes_active_print']
    assert [(row['channel'], row['remaining'], row['active_print_g']) for row in projected['rows']] == [
        ('3', 480, 20), ('1', 300, 0),
    ]
    assert projected['rows'][0]['deficit'] == 10
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()

    source = adapter.source('original', 'forecast')
    accounting.apply(key, 1, {'1': 0, '3': 5000}, state='active', source=source, basis='executed_gcode')
    monitor['state'] = 'paused'
    partial = forecast()
    assert partial['rows'][0]['remaining'] == 480
    assert partial['rows'][0]['active_print_g'] == 15
    assert [(r['used'], r['after']) for r in current_cards()] == [(20, 480)]
    monitor['state'] = 'complete'
    assert forecast()['rows'][0]['remaining'] == 480
    assert current_cards() == []
    accounting.apply(key, 2, {'1': 0, '3': 20000}, state='completed', source=source, basis='executed_gcode')
    final = forecast()
    assert final['rows'][0]['remaining'] == 480 and not final['includes_active_print']
    assert catalog.spool('04112233')['remaining_mg'] == 480000


def scenario(bench,auto=True,profile_overrides=None):
    store,c,fleet,adapter=bench
    fleet.states={'a':snapshot('a',{'3':'04112233','1':'04AABBCC'}),'b':snapshot('b',{})}
    with c.db:c.db.execute("UPDATE uid_spools SET remaining_mg=20000 WHERE uid='04112233'")
    start=c.inventory_snapshot('a',fleet.states)
    life=MotionLifecycle(adapter)
    key=life.start('a',filename='job.gcode',observed_at=1011,capture_id='recover',epoch='original',start=start,channels=['1','3'])['job_key']
    feed={'filament_feed right':{f'extruder{h}':dict(module_exist=True,disable_auto=False,filament_detected=True) for h in [1,3]}}
    # U1 groups are physical pairs: T1 is left, T3 is right.
    feed={'filament_feed left':{'extruder1':feed['filament_feed right']['extruder1']},'filament_feed right':{'extruder3':feed['filament_feed right']['extruder3']}}
    profile=dict(filename='job.gcode',started_at=1010.,file_sha256='a'*64,mapping=[0,1,2,3],replenished=[0,1,2,3],logical_weights=[0,0,0,70],parameters=[dict(diameter_mm=1.75,density_g_cm3=1.24)]*4,auto_replenish=auto,feed_start=feed)
    profile.update(profile_overrides or {})
    life.recovery_profile('a',history('in_progress'),profile);life.disconnected('a','Computer asleep')
    status=dict(print_stats=dict(state='complete',filename='job.gcode'),print_task_config=dict(auto_replenish_filament=auto,extruder_map_table=[0,1,2,1],extruders_replenished=[0,1,2,1]),**copy.deepcopy(feed))
    status['filament_feed right']['extruder3']['filament_detected']=False
    return life,key,status,c,fleet


def test_refill_calculated_once_with_original_remainders_and_restart(bench):
    life,key,status,c,fleet=scenario(bench)
    result=life.recovery_terminal('a',history('completed'),status,'a'*64)
    assert result['status']=='applied',result
    assert result['totals_mg']=={'1':50000,'3':20000}
    assert c.spool('04112233')['remaining_mg']==0
    assert c.spool('04AABBCC')['remaining_mg']==250000
    for _ in range(3):assert life.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='duplicate'
    restarted=MotionLifecycle(life.adapter)
    assert restarted.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='duplicate'
    assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==2
    assert json.loads(c.db.execute('SELECT payload FROM uid_recovery_receipts').fetchone()[0])['estimate_source']=='slicer_and_exhausted_remainder'


@pytest.mark.parametrize('fault',['off','unknown','changed_mode','no_runout','wrong_uid','wrong_file','plan_contradiction','quarantine','missing_target','multiple_transition','cancelled'])
def test_unproven_or_manual_replacements_do_not_debit(bench,fault):
    life,key,status,c,fleet=scenario(bench,False if fault=='off' else None if fault=='unknown' else True)
    terminal=history('completed');digest='a'*64
    if fault=='changed_mode':status['print_task_config']['auto_replenish_filament']=False
    if fault=='no_runout':status['filament_feed right']['extruder3']['filament_detected']=True
    if fault=='wrong_uid':fleet.states['a']['channels']['1']['uid']='04FFFFFF'
    if fault=='wrong_file':digest='b'*64
    if fault=='quarantine':
        with c.db:c.db.execute('UPDATE uid_recovery_profiles SET quarantined=1')
    if fault=='plan_contradiction':
        r=c.db.execute('SELECT history_key,profile FROM uid_recovery_profiles').fetchone();p=json.loads(r[1]);p['logical_weights'][3]=10
        with c.db:c.db.execute('UPDATE uid_recovery_profiles SET profile=?',(json.dumps(p),))
    if fault=='missing_target':
        with c.db:c.db.execute("DELETE FROM uid_job_tools WHERE channel='1'")
    if fault=='multiple_transition':status['print_task_config']['extruders_replenished']=[1,1,2,1]
    if fault=='cancelled':terminal=history('cancelled')
    assert life.recovery_terminal('a',terminal,status,digest)['status']=='review'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


@pytest.mark.parametrize('auto',[False,True])
def test_no_transition_uses_history_counter_and_preserves_other_spool(bench,auto):
    life,key,status,c,fleet=scenario(bench,auto)
    status['print_task_config'].update(extruder_map_table=[0,1,2,3],extruders_replenished=[0,1,2,3])
    status['filament_feed right']['extruder3']['filament_detected']=True
    h=history('completed');h['filament_used']=100
    r=life.recovery_terminal('a',h,status,'a'*64)
    assert r['status']=='applied',r
    assert c.spool('04112233')['remaining_mg']==19702
    assert c.spool('04AABBCC')['remaining_mg']==300000


def test_remote_outbox_and_receipt_are_atomic_and_old_backup_cannot_replay(bench):
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    from tracker_uid_backup import export,restore,fingerprint
    life,key,status,c,fleet=scenario(bench)
    accounting=life.adapter.service.accounting;Library(accounting);Delivery(accounting)
    for n,uid in enumerate(['04112233','04AABBCC'],1):
        with c.db:c.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(c.spool(uid)['spool_id'],'http://127.0.0.1:18899',n))
    before=export(c.db)
    assert life.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='applied'
    assert [(r['delta_mg'],r['state']) for r in c.db.execute('SELECT * FROM uid_remote_outbox ORDER BY remote_id')]==[(20000,'held'),(50000,'held')]
    for _ in range(3):life.recovery_terminal('a',history('completed'),status,'a'*64)
    assert c.db.execute('SELECT count(*) FROM uid_remote_outbox').fetchone()[0]==2
    restore(before,c.db,fingerprint(c.db))
    reopened=MotionLifecycle(life.adapter)
    assert reopened.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='review'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    assert not c.db.execute('SELECT * FROM uid_remote_outbox').fetchall()


def test_insufficient_target_rolls_back_receipt_and_all_spools(bench):
    life,key,status,c,fleet=scenario(bench)
    target=c.spool('04AABBCC')['spool_id'];ctx=json.loads(c.db.execute('SELECT context FROM uid_motion_starts WHERE job_key=?',(key,)).fetchone()[0]);ctx['start']['spools'][target]['remaining_g']=30
    with c.db:
        c.db.execute('UPDATE uid_spools SET remaining_mg=30000 WHERE spool_id=?',(target,))
        c.db.execute('UPDATE uid_motion_starts SET context=? WHERE job_key=?',(json.dumps(ctx),key))
    assert life.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='review'
    assert c.spool('04112233')['remaining_mg']==20000
    assert not c.db.execute('SELECT * FROM uid_recovery_receipts').fetchall()
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_duplicate_uid_across_printers_blocks_automatic_recovery(bench):
    life,key,status,c,fleet=scenario(bench)
    fleet.states['b']=snapshot('b',{'1':'04AABBCC'})
    assert life.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='review'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_tester_material_two_to_t3_timeout_then_completion_and_replay(bench):
    # Sanitized facts from the Windows 1.3.3 report: material 2, 1.55 g, T3.
    mapping=[0,3,2,3]
    life,key,status,c,fleet=scenario(bench,auto=False,profile_overrides=dict(
        mapping=mapping,logical_weights=[0,1.55,0,0]))
    status['print_task_config'].update(extruder_map_table=mapping,extruders_replenished=[0,1,2,3])
    status['filament_feed right']['extruder3']['filament_detected']=True
    life.history('a',[history('completed')])
    preview=life.recovery_preview(key)
    assert preview['totals_mg']=={'3':1550} and not preview['authorizes_debit']
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    # Missing terminal evidence cannot be replaced with guessed identity mapping.
    missing=copy.deepcopy(status);missing['print_task_config']['extruder_map_table']=[]
    assert life.recovery_terminal('a',history('completed'),missing,'a'*64)['status']!='applied'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    result=life.recovery_terminal('a',history('completed'),status,'a'*64)
    assert result['status']=='applied' and result['totals_mg']['3']==1550
    assert c.spool('04112233')['remaining_mg']==18450
    assert c.spool('04AABBCC')['remaining_mg']==300000
    restarted=MotionLifecycle(life.adapter)
    for _ in range(3):
        assert restarted.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='duplicate'
    assert c.db.execute('SELECT count(*) FROM uid_debits WHERE delta_mg>0').fetchone()[0]==1


def test_orange_and_black_remap_debits_only_the_confirmed_heads(bench):
    _, catalog, fleet, adapter = bench
    fleet.states = {'a': snapshot('a', {'0': '04AABBCC', '2': '04112233'})}
    lifecycle = MotionLifecycle(adapter)
    mapping = [2, 0, 2, 3]
    feed = {
        'filament_feed left': {'extruder0': dict(filament_detected=True)},
        'filament_feed right': {'extruder2': dict(filament_detected=True)},
    }
    job = history('in_progress')
    profile = dict(filename=job['filename'], started_at=job['start_time'], file_sha256='a' * 64,
                   mapping=mapping, replenished=[0, 1, 2, 3], logical_weights=[15.08, 2.36, 0, 0],
                   parameters=[None] * 4, auto_replenish=False, feed_start=feed)
    start = catalog.inventory_snapshot('a', fleet.states)
    lifecycle.start('a', filename=job['filename'], observed_at=1011, capture_id='remap',
                    epoch='first', start=start, channels=['0', '2'])
    lifecycle.recovery_profile('a', job, profile)
    lifecycle.disconnected('a', 'Test interruption')
    status = dict(print_stats=dict(state='complete', filename=job['filename']),
                  print_task_config=dict(auto_replenish_filament=False, extruder_map_table=mapping,
                                         extruders_replenished=[0, 1, 2, 3]), **feed)
    missing = copy.deepcopy(status)
    missing['print_task_config']['extruder_map_table'] = []
    assert lifecycle.recovery_terminal('a', history('completed'), missing, 'a' * 64)['status'] == 'review'
    assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    result = lifecycle.recovery_terminal('a', history('completed'), status, 'a' * 64)
    assert result['status'] == 'applied', result
    assert result['totals_mg'] == {'0': 2360, '2': 15080}
    assert catalog.spool('04AABBCC')['remaining_mg'] == 297640
    assert catalog.spool('04112233')['remaining_mg'] == 484920
    assert lifecycle.recovery_terminal('a', history('completed'), status, 'a' * 64)['status'] == 'duplicate'


def test_shared_head_for_used_materials_still_requires_distribution_review(bench):
    life,key,status,c,fleet=scenario(bench,auto=False,profile_overrides=dict(
        mapping=[0,3,2,3],logical_weights=[0,1.55,0,2]))
    life.history('a',[history('completed')])
    with pytest.raises(ValueError,match='distribution review'):
        life.recovery_preview(key)
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


@pytest.mark.parametrize('fault', [None, 'gap', 'runout', 'insertion', 'tag_change', 'mapping', 'other_head', 'wrong_file'])
@pytest.mark.parametrize('reader_present', [False, True])
def test_manual_completed_estimate_requires_original_placement(bench, fault, reader_present):
    from test_manual_without_uid import stock
    from test_uid_motion_adapter import evidence
    store, catalog, fleet, adapter = bench
    fleet.states['a'] = snapshot('a', {}) if reader_present else stock(snapshot('a', {}))
    accounting = adapter.service.accounting
    sid = catalog.register_manual('T0 PLA', 553177)['spool_id']
    accounting.assign_manual('a', '0', sid, fleet.states, confirmed=True)
    life = MotionLifecycle(adapter)
    e = evidence(store)
    e.update(start=catalog.inventory_snapshot('a', fleet.states), terminal_state='completed',
             comparison={'matches': False, 'printer_total_mm': None}, mapping_consistent=True)
    e['feed']['runouts'] = [False] * 4
    feed = {'filament_feed left': {'extruder0': {'filament_detected': True}}}
    profile = e['profile']
    profile.update(file_sha256='a'*64, logical_weights=[18.42,0,0,0],
                   replenished=[0,1,2,3], auto_replenish=False, feed_start=feed)
    life.start('a', filename='job.gcode', observed_at=1010., capture_id=e['capture_id'],
               epoch=e['epoch'], start=e['start'], channels=['0'])
    life.recovery_profile('a', history(), profile)
    if fault == 'gap': life.disconnected('a')
    if fault == 'runout': e['feed']['runouts'][0] = True
    if fault == 'insertion': e['feed']['insertions'][0] = True
    if fault == 'tag_change': e['tags']['unchanged'][0] = False
    if fault == 'mapping': e['mapping_consistent'] = False
    if fault == 'other_head': e['heads'][1]['net_mm'] = 100
    if fault == 'wrong_file': e['profile']['file_sha256'] = 'b'*64
    life.terminal('a', e)
    status = dict(print_stats=dict(state='complete', filename='job.gcode'),
                  print_task_config=dict(auto_replenish_filament=False, extruder_map_table=[0,1,2,3],
                                         extruders_replenished=[0,1,2,3]), **feed)
    def finish():
        return life.recovery_terminal('a', history('completed'), status, 'a'*64)['status']
    if fault:
        assert finish() == 'review'
        assert catalog.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 0
    else:
        assert finish() == 'applied'
        assert finish() == 'duplicate'
        assert catalog.db.execute('SELECT remaining_mg FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()[0] == 534757


@pytest.mark.parametrize('fault', [None, 'placement_after_start', 'cancelled', 'socket_gap',
                                   'feed_change', 'file_changed', 'terminal_only'])
def test_late_attachment_two_manual_spools(bench, monkeypatch, fault):
    import socket
    import time
    from test_manual_without_uid import stock
    from test_uid_motion_adapter import evidence
    from tracker_uid_runtime import history_read_timeout

    store, catalog, fleet, adapter = bench
    fleet.states['a'] = stock(snapshot('a', {}))
    accounting = adapter.service.accounting
    monkeypatch.setattr(time, 'time', lambda: 1100 if fault == 'placement_after_start' else 1000)
    for channel, balance in [('0', 553177), ('1', 194600)]:
        spool = catalog.register_manual('T' + channel, balance, spool_id='manual-' + channel)
        accounting.assign_manual('a', channel, spool['spool_id'], fleet.states, confirmed=True)
    life = MotionLifecycle(adapter)
    job = history(start=1010.)
    e = evidence(store)
    profile = dict(e['profile'], filename=job['filename'], started_at=job['start_time'],
                   history_job_id=job['job_id'], logical_weights=[64.62, .77, 0, 0],
                   file_sha256='a'*64, auto_replenish=True, replenished=[0,1,2,3], mapping=[0,1,2,3])
    e.update(profile=profile, terminal_state='completed', complete=False, observed_from_attachment=True,
             mapping_consistent=True)
    e['feed']['runouts'] = [False]*4
    status = dict(print_stats=dict(state='complete', filename=job['filename']),
                  print_task_config=dict(auto_replenish_filament=True, extruder_map_table=list(range(4))+[0]*28,
                                         extruders_replenished=[0,1,2,3]))
    status['filament_feed left'] = {'extruder'+i: {'filament_detected':True} for i in ('0','1')}
    ended = dict(job, status='completed')
    if fault != 'terminal_only':
        placement = life.attach_active('a',profile,3395.59,e['epoch'],e['capture_id'])
        if fault == 'placement_after_start':
            assert placement is None
        else:
            assert placement
            e['start'] = placement
            assert history_read_timeout(socket.timeout())
            life.history_timeout('a','timed out')
            if fault == 'socket_gap':
                life.disconnected('a','Motion stream ended')
            if fault == 'feed_change':
                e['feed']['runouts'][1] = True
            if fault == 'cancelled':
                ended['status'] = e['terminal_state'] = 'cancelled'
                status['print_stats']['state'] = 'cancelled'
            life.terminal('a',e)
    digest = 'b'*64 if fault == 'file_changed' else profile['file_sha256']
    def finish():
        return life.recovery_terminal('a',ended,status,digest)['status']
    if fault:
        assert finish() != 'applied'
        assert not catalog.db.execute('SELECT * FROM uid_debits').fetchall()
    else:
        assert finish() == 'applied'
        for _ in range(3):
            assert finish() == 'duplicate'
        assert dict(catalog.db.execute('SELECT spool_id,delta_mg FROM uid_debits')) == {
            'manual-0':64620, 'manual-1':770}
        assert dict(catalog.db.execute("SELECT spool_id,remaining_mg FROM uid_spools WHERE uid IS NULL")) == {
            'manual-0':488557, 'manual-1':193830}
