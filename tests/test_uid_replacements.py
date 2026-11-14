import copy,json
import pytest
from test_uid_motion_adapter import bench,history
from test_uid_calculated_history import scenario


def setup(bench):
    life,key,status,c,fleet=scenario(bench,False)
    # Two initial UIDs, but only T3 prints. Replacement is a third registered UID.
    fleet.states['a']['epoch']='stable-reader-epoch'
    c.register('04CCCCDD','New spool',100000)
    status['print_task_config'].update(extruder_map_table=[0,1,2,3],extruders_replenished=[0,1,2,3])
    status['filament_feed right']['extruder3']['filament_detected']=True
    status['print_stats'].update(state='paused',filament_used=100)
    life.replacement_observe('a',history('in_progress'),status)
    return life,key,status,c,fleet


def swap(life,status,fleet):
    fleet.states['a']['channels']['3']['uid']='04CCCCDD'
    life.replacement_observe('a',history('in_progress'),status)


def finish(life,status):
    status['print_stats'].update(state='complete',filament_used=1000)
    h=history('completed');h['filament_used']=1000
    return life.recovery_terminal('a',h,status,'a'*64)


def test_paused_uid_change_allocates_without_consuming_whole_old_remainder(bench):
    life,key,status,c,fleet=setup(bench);swap(life,status,fleet)
    event=life.replacements.events(key)[0];assert event['proven'],event
    for _ in range(3):life.replacement_observe('a',history('in_progress'),status)
    assert len(life.replacements.events(key))==1
    result=finish(life,status);assert result['status']=='applied',result
    assert c.spool('04112233')['remaining_mg']==19702 # 298 mg, NOT all 20 g
    assert c.spool('04CCCCDD')['remaining_mg']==97315 # 2983 total minus 298
    assert c.spool('04AABBCC')['remaining_mg']==300000
    assert finish(life,status)['status']=='duplicate'
    assert c.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]==2


@pytest.mark.parametrize('fault',['printing','counter_changed','gap','unknown_uid','counter_reset'])
def test_unproven_replacement_stays_journalled_without_debit(bench,fault):
    life,key,status,c,fleet=setup(bench)
    if fault=='printing':status['print_stats']['state']='printing'
    if fault=='counter_changed':status['print_stats']['filament_used']=150
    if fault=='counter_reset':status['print_stats']['filament_used']=0
    if fault=='gap':life.disconnected('a','Computer asleep')
    swap(life,status,fleet)
    if fault=='unknown_uid':
        # A further unregistered tag must not become a newly invented spool.
        fleet.states['a']['channels']['3']['uid']='04EEEEFF';life.replacement_observe('a',history('in_progress'),status)
    assert finish(life,status)['status']=='review'
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    assert life.replacements.events(key)


def test_empty_slot_during_paused_removal_and_sleep_after_logged_change(bench):
    from tracker_uid_motion_lifecycle import MotionLifecycle
    life,key,status,c,fleet=setup(bench)
    obs=fleet.states['a']['channels']['3'];obs.update(state='absent',uid=None)
    life.replacement_observe('a',history('in_progress'),status)
    obs.update(state='present',uid='04CCCCDD');life.replacement_observe('a',history('in_progress'),status)
    assert life.replacements.events(key)[0]['proven']
    life.disconnected('a','Sleep after replacement')
    life=MotionLifecycle(life.adapter)
    assert finish(life,status)['status']=='applied'
    assert finish(life,status)['status']=='duplicate'


def test_replacement_before_start_has_no_old_spool_consumption(bench):
    from test_uid_accounting import snapshot
    from tracker_uid_motion_lifecycle import MotionLifecycle
    store,c,fleet,adapter=bench
    with c.db:c.db.execute("UPDATE uid_spools SET remaining_mg=5000 WHERE uid='04112233'")
    c.register('04CCCCDD','Fresh spool',100000)
    fleet.states={'a':dict(snapshot('a',{'0':'04CCCCDD'}),epoch='stable')}
    life=MotionLifecycle(adapter);start=c.inventory_snapshot('a',fleet.states)
    key=life.start('a',filename='job.gcode',observed_at=1011,capture_id='before',epoch='capture',start=start,channels=['0'])['job_key']
    feed={'filament_feed left':{'extruder0':dict(module_exist=True,disable_auto=False,filament_detected=True)}}
    profile=dict(filename='job.gcode',started_at=1010.,file_sha256='a'*64,mapping=[0,1,2,3],replenished=[0,1,2,3],logical_weights=[25,0,0,0],parameters=[dict(diameter_mm=1.75,density_g_cm3=1.24)]*4,auto_replenish=False,feed_start=feed)
    life.recovery_profile('a',history('in_progress'),profile);life.disconnected('a','sleep')
    status=dict(print_stats=dict(state='complete',filename='job.gcode'),print_task_config=dict(auto_replenish_filament=False,extruder_map_table=[0,1,2,3],extruders_replenished=[0,1,2,3]),**feed)
    assert life.recovery_terminal('a',history('completed'),status,'a'*64)['status']=='applied'
    assert c.spool('04112233')['remaining_mg']==5000
    assert c.spool('04CCCCDD')['remaining_mg']==75000
    assert life.replacements.events(key)==[]


def test_insufficient_new_spool_rolls_back_all_segments(bench):
    life,key,status,c,fleet=setup(bench)
    with c.db:c.db.execute("UPDATE uid_spools SET remaining_mg=1000 WHERE uid='04CCCCDD'")
    swap(life,status,fleet)
    assert finish(life,status)['status']=='review'
    assert c.spool('04112233')['remaining_mg']==20000
    assert c.spool('04CCCCDD')['remaining_mg']==1000
    assert not c.db.execute('SELECT * FROM uid_recovery_receipts').fetchall()
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()


def test_manual_segments_remote_queue_and_restore_do_not_repeat(bench):
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    from tracker_uid_backup import export,restore,fingerprint
    life,key,status,c,fleet=setup(bench);swap(life,status,fleet)
    Library(life.adapter.service.accounting);Delivery(life.adapter.service.accounting)
    for n,uid in enumerate(['04112233','04CCCCDD'],1):
        with c.db:c.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(c.spool(uid)['spool_id'],'http://127.0.0.1:18899',n))
    backup=export(c.db)
    assert finish(life,status)['status']=='applied'
    assert [(r['delta_mg'],r['state']) for r in c.db.execute('SELECT * FROM uid_remote_outbox ORDER BY remote_id')]==[(298,'held'),(2685,'held')]
    assert finish(life,status)['status']=='duplicate'
    restore(backup,c.db,fingerprint(c.db))
    assert finish(life,status)['status']=='review'
    assert not c.db.execute('SELECT * FROM uid_remote_outbox').fetchall()
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
