import copy,json
import pytest
from test_uid_motion_adapter import bench,history
from test_uid_accounting import snapshot
from tracker_uid_motion_lifecycle import MotionLifecycle


def scenario(bench,auto=True):
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
