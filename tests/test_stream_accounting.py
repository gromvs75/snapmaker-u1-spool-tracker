import copy
import pytest
from test_accounting import setup_plan, job, remaining
from accounting import apply_history_job, commit_stream_estimate, commit_unchanged_slicer_estimate, run_key


def make_evidence(store):
    return {'complete': True, 'continuous': True, 'comparison': {'matches': True, 'printer_total_mm': 300},
            'feed': {'valid': True, 'covered': [True]*4, 'insertions': [False]*4},
            'tags': {'known': True, 'unchanged': [True]*4, 'initial': [None]*4},
            'capture_id': 'capture-1', 'epoch': 'session-1', 'start': store.read(),
            'heads': [{'head': i, 'net_mm': n} for i,n in enumerate((100, 200, 0, 0))],
            'profile': {'filename': 'job.gcode', 'started_at': 1010.0, 'mapping': [0, 1, 2, 3],
                        'logical_weights': [2, 0, 0, 0], 'filament_type': 'PLA;PLA;PLA;PLA',
                        'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}}


def setup_job(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()['printer']
    active = job()
    assert apply_history_job(store, config, active, fingerprint, {'mapping': [0, 1, 2, 3], 'auto_replenish': True}) == 'review'
    evidence = make_evidence(store)
    assert apply_history_job(store, config, job(status='completed')) == 'review'
    return store, run_key(config, active), evidence


def slicer_evidence(store, source):
    evidence = copy.deepcopy(source)
    evidence['profile']['logical_weights'] = [10, 20, 30, 40]
    evidence['profile']['replenished'] = [0, 1, 2, 3]
    evidence['feed']['runouts'] = [False] * 4
    evidence['mapping_unchanged'] = True
    return evidence


def test_slicer_estimate_after_successful_resume_is_debited_once(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    evidence = slicer_evidence(store, evidence)
    evidence['comparison'] = {'matches': False}  # Counter rewind at resume does not reject slicer estimate.
    assert commit_unchanged_slicer_estimate(store, key, evidence) is True
    assert remaining(store) == [990, 980, 970, 960]
    assert commit_unchanged_slicer_estimate(store, key, evidence) is False
    assert remaining(store) == [990, 980, 970, 960]


@pytest.mark.parametrize('fault', ['runout', 'insertion', 'sensor', 'tag', 'mapping', 'changed_balance', 'cancel', 'other_review', 'profile'])
def test_slicer_never_guesses_when_replacement_or_identity_uncertain(tmp_path, fault):
    store, key, evidence = setup_job(tmp_path)
    evidence = slicer_evidence(store, evidence)
    if fault == 'runout': evidence['feed']['runouts'][0] = True
    if fault == 'insertion': evidence['feed']['insertions'][0] = True
    if fault == 'sensor': evidence['feed']['covered'][0] = False
    if fault == 'tag': evidence['tags']['unchanged'][0] = False
    if fault == 'mapping': evidence['mapping_unchanged'] = False
    if fault == 'profile': evidence['profile']['started_at'] += 1
    if fault == 'changed_balance': store.update(lambda db: db['spools']['spool0'].__setitem__('remaining_g', 999))
    if fault == 'cancel': store.update(lambda db: db['runs'][key].__setitem__('terminal_status', 'cancelled'))
    if fault == 'other_review': store.update(lambda db: db['runs'][key].__setitem__('review_reason', 'Connection lost'))
    with pytest.raises(ValueError):
        commit_unchanged_slicer_estimate(store, key, evidence)
    assert remaining(store) == ([999, 1000, 1000, 1000] if fault == 'changed_balance' else [1000]*4)


@pytest.mark.parametrize('subscription_has_mapping', [True, False])
@pytest.mark.parametrize('pause_state', ['paused', 'error'])
def test_live_slicer_path_handles_pause_counter_rewind(tmp_path, monkeypatch, subscription_has_mapping, pause_state):
    import time
    from motion_stream import MotionStreamRecorder
    store, key, evidence = setup_job(tmp_path)
    profile = slicer_evidence(store, evidence)['profile']
    tick = {'value': 0.0}
    def monotonic():
        tick['value'] += 1
        return tick['value']
    monkeypatch.setattr(time, 'monotonic', monotonic)
    monkeypatch.setattr(time, 'time', lambda: 1010.0)
    recorder = MotionStreamRecorder(store)
    channel = {'module_exist': True, 'disable_auto': False, 'filament_detected': True}
    initial = {'print_stats': {'state': 'standby', 'filename': ''},
               'print_task_config': {'extruder_map_table': [0, 1, 2, 3], 'extruders_replenished': [0, 1, 2, 3]},
               'filament_detect': {'state': [0]*4, 'info': [{'CARD_UID': 0} for _ in range(4)]},
               'filament_feed left': {'extruder0': channel, 'extruder1': channel},
               'filament_feed right': {'extruder2': channel, 'extruder3': channel}}
    if not subscription_has_mapping:
        del initial['print_task_config']
    class Socket:
        def __init__(self):
            self.items = [{'id': 10, 'result': {'status': initial}},
                          *[{'id': n, 'result': {'header': []}} for n in (1, 2, 3, 4)],
                          {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'job.gcode'}}}},
                          {'method': 'notify_tracker_head_0', 'params': {'data': [[1, 1, 100, 0, [0,0,0], [1,0,0]]]}},
                          {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': pause_state, 'filament_used': 100}}}},
                          {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filament_used': 50}}}},
                          {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'complete', 'filament_used': 50}}}}]
            self.count = 0
        def send(self, payload): pass
        def receive(self):
            if self.items:
                item = self.items.pop(0)
                if item.get('method') == 'notify_tracker_head_0': store._motion_slicer_profile = profile
                return item
            self.count += 1
            if self.count > 15 or store.read()['runs'][key]['status'] == 'committed': recorder.stop_event.set()
            return None
    try:
        recorder._capture(Socket(), store.read()['printer'])
        assert remaining(store) == [990, 980, 970, 960]
        assert store.read()['runs'][key]['status'] == 'committed'
    finally:
        recorder.stop()


def test_auto_refill_estimate_is_atomic_and_never_debits_twice(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    assert commit_stream_estimate(store, key, evidence) is True
    assert remaining(store) == [999.702, 999.403, 1000, 1000]
    assert commit_stream_estimate(store, key, evidence) is False
    assert remaining(store) == [999.702, 999.403, 1000, 1000]
    assert store.read()['runs'][key]['accounting_method'] == 'motion_estimate'


@pytest.mark.parametrize('fault', ['incomplete', 'disconnect', 'checksum', 'sensor', 'insertion', 'profile', 'slot', 'tag', 'balance'])
def test_uncertain_auto_refill_never_changes_balances(tmp_path, fault):
    store, key, evidence = setup_job(tmp_path)
    if fault == 'incomplete': evidence['complete'] = False
    if fault == 'disconnect': evidence['continuous'] = False
    if fault == 'checksum': evidence['comparison']['matches'] = False
    if fault == 'sensor': evidence['feed']['covered'][1] = False
    if fault == 'insertion': evidence['feed']['insertions'][1] = True
    if fault == 'profile': evidence['profile']['started_at'] += 1
    if fault == 'slot': store.update(lambda db: db['slots'].__setitem__('1', 'spool3'))
    if fault == 'tag': evidence['tags']['unchanged'][1] = False
    if fault == 'balance': store.update(lambda db: db['spools']['spool1'].__setitem__('remaining_g', 999))
    with pytest.raises(ValueError): commit_stream_estimate(store, key, evidence)
    assert remaining(store) == ([1000, 999, 1000, 1000] if fault == 'balance' else [1000] * 4)
    assert store.read()['runs'][key]['status'] == 'review'


@pytest.mark.parametrize('fresh_profile', [True, False])
@pytest.mark.parametrize('pause_and_resume', [True, False])
@pytest.mark.parametrize('terminal_state', ['complete', 'cancelled'])
def test_live_stream_pipeline_books_automatic_replacement_estimate(tmp_path, monkeypatch, fresh_profile, pause_and_resume, terminal_state):
    import json
    import time
    from motion_stream import MotionStreamRecorder
    store, key, evidence = setup_job(tmp_path)
    if terminal_state == 'cancelled':
        store.update(lambda db: db['runs'][key].__setitem__('terminal_status', 'cancelled'))
    profile = evidence['profile']
    if not fresh_profile:
        store._motion_slicer_profile = profile
    tick = {'value': 0.0}
    def monotonic():
        tick['value'] += 1.0
        return tick['value']
    monkeypatch.setattr(time, 'monotonic', monotonic)
    monkeypatch.setattr(time, 'time', lambda: 1010.0)
    recorder = MotionStreamRecorder(store)
    channel = {'module_exist': True, 'disable_auto': False, 'filament_detected': True}
    scan = {'state': [0]*4, 'info': [{'CARD_UID': 0} for _ in range(4)]}
    initial = {'print_stats': {'state': 'standby', 'filename': ''}, 'filament_detect': scan,
               'filament_feed left': {'extruder0': channel, 'extruder1': channel},
               'filament_feed right': {'extruder2': channel, 'extruder3': channel}}
    class FakeSocket:
        def __init__(self):
            self.responses = [{'id': 10, 'result': {'status': initial}},
                *[{'id': n, 'result': {'header': []}} for n in (1, 2, 3, 4)],
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'job.gcode', 'filament_used': 0}}}},
                {'method': 'notify_tracker_head_0', 'params': {'data': [[1, 1, 100, 0, [0,0,0], [1,0,0]]]}},
                {'method': 'notify_tracker_status', 'params': {'status': {'filament_feed left': {'extruder0': {'filament_detected': False}}}}},
                {'method': 'notify_tracker_head_1', 'params': {'data': [[2, 1, 200, 0, [0,0,0], [1,0,0]]]}},
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': terminal_state, 'filament_used': 300.12 if terminal_state == 'cancelled' else 300}}}},
                # Real printers continue to emit other status updates after
                # cancellation; they must not erase the pending accounting.
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'filament_used': 300}}}}]
            if terminal_state == 'cancelled':
                # U1 can retract after the terminal counter has frozen. That
                # later movement must not invalidate the pre-cancel snapshot.
                self.responses.insert(-1, {'method': 'notify_tracker_head_0', 'params': {'data': [
                    [3, 1, .12, 0, [0,0,0], [1,0,0]], [4, 1, -2, 0, [0,0,0], [1,0,0]]]}})
            if pause_and_resume:
                # Pause/resume must not reset the captured heads or count a job twice.
                self.responses[7:7] = [
                    {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'paused', 'filament_used': 100}}}},
                    {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'job.gcode', 'filament_used': 100}}}},
                ]
            self.empty = 0
        def send(self, payload): pass
        def receive(self):
            if self.responses:
                item = self.responses.pop(0)
                if fresh_profile and item.get('method') == 'notify_tracker_head_0': store._motion_slicer_profile = profile
                return item
            self.empty += 1
            if self.empty > 12 or store.read()['runs'][key]['status'] == 'committed':
                recorder.stop_event.set()
            return None
    try:
        recorder._capture(FakeSocket(), store.read()['printer'])
        records = [json.loads(line) for line in (store.directory/'motion-diagnostic.jsonl').read_text().splitlines()]
        assert any(x['kind'] == 'auto_accounting_committed' for x in records) is fresh_profile
        expected = [999.701, 999.403, 1000, 1000] if terminal_state == 'cancelled' else [999.702, 999.403, 1000, 1000]
        assert remaining(store) == (expected if fresh_profile else [1000]*4)
    finally:
        recorder.stop()


def test_stream_without_total_or_with_wrong_total_remains_review(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    evidence['comparison'] = None
    with pytest.raises(ValueError, match='printer total'):
        commit_stream_estimate(store, key, evidence)
    assert remaining(store) == [1000] * 4
    evidence['comparison'] = {'matches': False}
    with pytest.raises(ValueError, match='printer total'):
        commit_stream_estimate(store, key, evidence)
    assert remaining(store) == [1000] * 4


def test_cancelled_job_books_only_verified_partial_motion_once(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    def cancel(db):
        db['runs'][key]['terminal_status'] = 'cancelled'
    store.update(cancel)
    assert commit_stream_estimate(store, key, evidence) is True
    assert remaining(store) == [999.702, 999.403, 1000, 1000]
    assert commit_stream_estimate(store, key, evidence) is False
    assert remaining(store) == [999.702, 999.403, 1000, 1000]
    assert store.read()['runs'][key]['terminal_status'] == 'cancelled'


def test_cancelled_job_never_books_full_slicer_plan(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    evidence = slicer_evidence(store, evidence)
    store.update(lambda db: db['runs'][key].__setitem__('terminal_status', 'cancelled'))
    with pytest.raises(ValueError, match='eligible'):
        commit_unchanged_slicer_estimate(store, key, evidence)
    assert remaining(store) == [1000] * 4


def test_resumed_u1_mismatched_motion_must_not_be_automatically_booked(tmp_path):
    # Anonymized totals from the October 29 pause/resume incident. These are
    # commanded lengths, not scale measurements and not spool identity proof.
    store, key, evidence = setup_job(tmp_path)
    evidence['heads'][0]['net_mm'] = 25483.020
    evidence['heads'][1]['net_mm'] = 0
    evidence['comparison'] = {'head_total_mm': 25483.020,
                              'printer_total_mm': 25428.631,
                              'difference_mm': 54.389, 'matches': False}
    with pytest.raises(ValueError, match='Motion differs'):
        commit_stream_estimate(store, key, evidence)
    assert remaining(store) == [1000] * 4
    assert store.read()['runs'][key]['status'] == 'review'


def test_reported_printer_counter_rewind_cannot_authorize_guessed_correction(tmp_path):
    # Anonymized observed counter values around pause/resume. The counter
    # rewind alone does not explain the final motion mismatch.
    store, key, evidence = setup_job(tmp_path)
    before_pause = 14526.618
    after_resume = 14490.705
    motion_total = 25483.020
    printer_total = 25428.631
    rewind = before_pause - after_resume
    unexplained = motion_total - (printer_total + rewind)
    assert rewind == pytest.approx(35.913)
    assert unexplained == pytest.approx(18.476)
    evidence['heads'][0]['net_mm'] = motion_total
    evidence['heads'][1]['net_mm'] = 0
    # Even a falsely asserted match must not bypass the independent amount check.
    evidence['comparison'] = {'matches': True, 'printer_total_mm': printer_total + rewind}
    with pytest.raises(ValueError, match='Motion differs'):
        commit_stream_estimate(store, key, evidence)
    assert remaining(store) == [1000] * 4
    assert store.read()['runs'][key]['status'] == 'review'


def test_pla_plus_spool_books_verified_motion_once_without_changing_other_spools(tmp_path):
    store, key, evidence = setup_job(tmp_path)
    store.update(lambda db: db['spools']['spool2'].update({'material': 'PLA. +'}))
    evidence['start'] = store.read()
    evidence['heads'] = [{'head': i, 'net_mm': 4010.699 if i == 2 else 0} for i in range(4)]
    evidence['comparison'] = {'matches': True, 'printer_total_mm': 4010.699}
    evidence['profile']['logical_weights'] = [0, 0, 11.27, 0]
    assert commit_stream_estimate(store, key, evidence) is True
    assert remaining(store) == [1000, 1000, 988.038, 1000]
    assert commit_stream_estimate(store, key, evidence) is False
    assert remaining(store) == [1000, 1000, 988.038, 1000]
