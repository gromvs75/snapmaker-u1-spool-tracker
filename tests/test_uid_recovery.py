import copy
import io
import pytest
from test_uid_motion_adapter import bench, evidence, history
from test_uid_motion_lifecycle import start
from tracker_uid_motion_lifecycle import MotionLifecycle
from tracker_uid_gcode_estimate import layer_estimates


def prepare(bench):
    store,c,fleet,adapter=bench;life=MotionLifecycle(adapter);e=evidence(store)
    key=start(life,'a',e)['job_key'];profile=copy.deepcopy(e['profile'])
    profile.update(file_sha256='a'*64,logical_weights=[1,0,0,0],mapping=[0,1,2,3],replenished=[0,1,2,3])
    profile['layers']={'2':dict(low_mm=[10,0,0,0],high_mm=[20,0,0,0])}
    life.recovery_profile('a',history('in_progress'),profile)
    life.disconnected('a','Computer slept')
    return life,key,c


def test_completed_plan_survives_gap_and_replay_without_debit(bench):
    life,key,c=prepare(bench)
    for _ in range(3):life.history('a',[history('completed')])
    p=life.recovery_preview(key)
    assert p['basis']=='completed_slicer_estimate' and p['totals_mg']=={'0':1000}
    assert p['requires_confirmation'] and not p['authorizes_debit']
    assert not c.db.execute('SELECT * FROM uid_debits').fetchall()
    reopened=MotionLifecycle(life.adapter)
    assert reopened.recovery_preview(key)['totals_mg']=={'0':1000}


def test_history_counter_preferred_and_error_layer_is_range(bench):
    life,key,c=prepare(bench);h=history('error');h['filament_used']=100
    life.history('a',[h]);p=life.recovery_preview(key)
    assert p['basis']=='printer_history_estimate' and p['totals_mg']=={'0':298}
    # Separate proposal from the same terminal status, no debit and no full-plan fallback.
    del h['filament_used'];life.history('a',[h])
    with pytest.raises(ValueError):life.recovery_preview(key)
    p=life.recovery_preview(key,2)
    assert p['basis']=='layer_range_estimate' and p['ranges_mg']=={'0':[30,60]}


def test_automatic_change_and_quarantined_plan_block_preview(bench):
    life,key,c=prepare(bench);life.history('a',[history('completed')])
    life.disconnected('a','Automatic transition requires research; debit blocked')
    with pytest.raises(ValueError,match='Automatic'):life.recovery_preview(key)
    c.db.execute('DELETE FROM uid_motion_review');c.db.execute('UPDATE uid_recovery_profiles SET quarantined=1');c.db.commit()
    with pytest.raises(ValueError,match='trusted'):life.recovery_preview(key)


def test_gcode_layer_range_uses_extrusion_not_layer_fraction():
    raw=b'M83\nG1 E10\nSET_PRINT_STATS_INFO CURRENT_LAYER=1\nG1 E2\nG1 E-1\nG1 E1\nSET_PRINT_STATS_INFO CURRENT_LAYER=2\nG1 E30\n'
    layers=layer_estimates(io.BytesIO(raw))
    assert layers['1']==dict(low_mm=[10,0,0,0],high_mm=[12,0,0,0])
    assert layers['2']==dict(low_mm=[12,0,0,0],high_mm=[42,0,0,0])
    assert layer_estimates(io.BytesIO(b'M83\nG1 E3'))=={}
    with pytest.raises(ValueError):layer_estimates(io.BytesIO(b'M200 D1.75'))


def test_changed_saved_plan_is_quarantined(bench):
    life,key,c=prepare(bench)
    row=c.db.execute('SELECT history_key,profile FROM uid_recovery_profiles').fetchone()
    import json
    p=json.loads(row['profile']);p['logical_weights']=[2,0,0,0]
    with pytest.raises(ValueError,match='changed'):life.recovery.remember(row['history_key'],p)
    life.history('a',[history('completed')])
    with pytest.raises(ValueError,match='trusted'):life.recovery_preview(key)


@pytest.mark.parametrize('line',[b'G1 E1E3',b'G1X1E2',b'G1 EINF',b'G1 ENAN'])
def test_unsupported_extrusion_syntax_is_not_silently_estimated(line):
    with pytest.raises(ValueError):layer_estimates(io.BytesIO(line))
