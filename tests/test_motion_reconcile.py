import copy
import pytest
from motion_reconcile import estimate_capture, MotionEvidenceError


def example():
    start = {'state': 'active', 'valid': True, 'identity_verified': True, 'epoch': 'e', 'capture_id': 'id',
             'filename': 'job.gcode', 'started_at': 1000, 'initial_tag_uids': ['01020304', '05060708', None, None]}
    end = {**start, 'state': 'completed', 'finished_at': 1100, 'head_mm': [100, 50, 0, 0], 'spool_insert_events': [False]*4,
           'final_tag_uids': list(start['initial_tag_uids'])}
    job = {'filename': 'job.gcode', 'status': 'completed', 'start_time': 1001}
    slots = ['a', 'b', '', '']
    values = {'a': {'uid': '01020304', 'diameter_mm': 1.75, 'density_g_cm3': 1.24},
              'b': {'uid': '05060708', 'diameter_mm': 1.75, 'density_g_cm3': 1.24}}
    return start, end, job, slots, values


def test_two_physical_heads_produce_separate_calibrated_estimates():
    start, end, job, slots, vals = example()
    result = estimate_capture(start, end, job, slots, slots, vals, copy.deepcopy(vals))
    assert result['a'] == pytest.approx(.298, abs=.001)
    assert result['b'] == pytest.approx(.149, abs=.001)


def test_untagged_spool_requires_manual_binding_and_continuity_evidence():
    start, end, job, slots, vals = example()
    start['initial_tag_uids'][1] = None
    end['initial_tag_uids'] = list(start['initial_tag_uids'])
    end['final_tag_uids'] = list(start['initial_tag_uids'])
    vals['b']['uid'] = None
    vals['b']['identity_mode'] = 'manual_confirmed'
    with pytest.raises(MotionEvidenceError, match='continuity'):
        estimate_capture(start, end, job, slots, slots, vals, copy.deepcopy(vals))
    end['manual_continuity'] = [False, True, False, False]
    assert estimate_capture(start, end, job, slots, slots, vals, copy.deepcopy(vals))['b'] == pytest.approx(.149, abs=.001)
    end['spool_insert_events'][1] = True
    with pytest.raises(MotionEvidenceError, match='identity'):
        estimate_capture(start, end, job, slots, slots, vals, copy.deepcopy(vals))


@pytest.mark.parametrize('fault', ['unverified', 'capture', 'job', 'missing_tag', 'inserted', 'calibration', 'slots', 'changed_final_tag', 'missing_final_snapshot'])
def test_ambiguous_capture_never_produces_an_estimate(fault):
    start, end, job, slots, vals = example()
    current_slots, current_vals = list(slots), copy.deepcopy(vals)
    if fault == 'unverified': end['identity_verified'] = False
    if fault == 'capture': end['capture_id'] = 'another'
    if fault == 'job': job['start_time'] += 50
    if fault == 'missing_tag': start['initial_tag_uids'][0] = end['initial_tag_uids'][0] = None
    if fault == 'inserted': end['spool_insert_events'][0] = True
    if fault == 'calibration': current_vals['a']['density_g_cm3'] = 1.1
    if fault == 'slots': current_slots[0] = 'other'
    if fault == 'changed_final_tag': end['final_tag_uids'][0] = 'deadbeef'
    if fault == 'missing_final_snapshot': end['final_tag_uids'] = None
    with pytest.raises(MotionEvidenceError):
        estimate_capture(start, end, job, slots, current_slots, vals, current_vals)
