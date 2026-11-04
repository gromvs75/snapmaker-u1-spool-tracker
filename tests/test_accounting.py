import json
import time
from io import BytesIO

import pytest

from accounting import apply_history_job, begin_motion_watch, commit_motion_watch, create_plan, fingerprint_file, invalidate_active_runs, reconcile_completed_review, run_key
from moonraker import MoonrakerClient, MoonrakerError, poll_once
from storage import SCHEMA_VERSION, Store

IDENTITY = {"mapping": [0, 1, 2, 3], "auto_replenish": False}


def setup_plan(tmp_path, weights=(10, 20, 30, 40), name="job.gcode"):
    store = Store(tmp_path / "data")
    store.read()
    def seed(db):
        db["printer"]["enabled"] = True
        for index in range(4):
            spool_id = f"spool{index}"
            db["spools"][spool_id] = {"name": spool_id, "material": "PLA", "remaining_g": 1000.0}
            db["slots"][str(index + 1)] = spool_id
    store.update(seed)
    file = tmp_path / name
    file.write_text("; filament used [g] = " + ",".join(str(x) for x in weights))
    snapshot = store.read()
    plan_id = create_plan(store, file, name, weights, snapshot, now=1000.0)
    fingerprint = fingerprint_file(file)
    return store, plan_id, fingerprint, file


def job(filename="job.gcode", status="in_progress", job_id="job-1", start=1010.0):
    return {"job_id": job_id, "filename": filename, "status": status,
            "start_time": start, "end_time": start + 100}


def remaining(store):
    return [store.read()["spools"][f"spool{i}"]["remaining_g"] for i in range(4)]


def test_planned_job_snapshot_and_no_export_debit(tmp_path):
    store, plan_id, fingerprint, file = setup_plan(tmp_path)
    plan = store.read()["plans"][plan_id]
    assert plan["status"] == "planned"
    assert plan["filename"] == "job.gcode"
    assert (plan["sha256"], plan["size"]) == fingerprint
    assert plan["weights"] == [10, 20, 30, 40]
    assert plan["spool_ids"] == ["spool0", "spool1", "spool2", "spool3"]
    create_plan(store, file, "job.gcode", [10, 20, 30, 40], store.read(), now=1001.0)
    assert remaining(store) == [1000] * 4


def test_unrelated_print_and_upload_do_not_debit(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    assert apply_history_job(store, store.read()["printer"], job(filename="other.gcode"), fingerprint) is None
    assert remaining(store) == [1000] * 4
    assert not store.read()["runs"]


def test_preflight_after_print_start_cannot_charge_old_job(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(status="completed", start=999.0), fingerprint) is None
    assert remaining(store) == [1000] * 4


def test_matching_start_and_success_exactly_once(tmp_path):
    store, plan_id, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    started = job()
    assert apply_history_job(store, config, started, fingerprint, IDENTITY) == "active"
    key = run_key(config, started)
    assert store.read()["runs"][key]["status"] == "active"
    assert remaining(store) == [1000] * 4
    completed = job(status="completed")
    assert apply_history_job(store, config, completed) == "committed"
    assert remaining(store) == [990, 980, 970, 960]
    assert store.read()["plans"][plan_id]["status"] == "committed"
    assert apply_history_job(store, config, completed) == "committed"
    assert remaining(store) == [990, 980, 970, 960]


def test_reviewed_job_error_then_same_job_resumes_and_completes(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()['printer']
    mapping = {'mapping': [0, 1, 2, 3], 'auto_replenish': True}
    assert apply_history_job(store, config, job(), fingerprint, mapping) == 'review'
    key = run_key(config, job())
    assert apply_history_job(store, config, job(status='error')) == 'review'
    assert store.read()['runs'][key]['terminal_status'] == 'error'
    assert apply_history_job(store, config, job(), mapping_evidence=mapping) == 'review'
    assert 'terminal_status' not in store.read()['runs'][key]
    assert apply_history_job(store, config, job(status='completed')) == 'review'
    assert store.read()['runs'][key]['terminal_status'] == 'completed'
    assert remaining(store) == [1000] * 4


def test_observed_print_without_export_plan_is_charged_once(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    started = job()
    assert apply_history_job(store, config, started, fingerprint, IDENTITY, [1, 2, 0, 0]) == "active"
    assert remaining(store) == [1000] * 4
    completed = job(status="completed")
    assert apply_history_job(store, config, completed) == "committed"
    assert apply_history_job(store, config, completed) == "committed"
    assert remaining(store) == [999, 998, 1000, 1000]


def test_observed_print_with_auto_replenishment_requires_review(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    uncertain = {"mapping": [0, 1, 2, 3], "auto_replenish": True}
    assert apply_history_job(store, config, job(), fingerprint, uncertain, [1, 0, 0, 0]) == "review"
    run = store.read()["runs"][run_key(config, job())]
    assert run["physical_weights"] == [1, 0, 0, 0]
    assert run["physical_spool_ids"] == ["spool0", "spool1", "spool2", "spool3"]
    assert apply_history_job(store, config, job(status="completed")) == "review"
    assert remaining(store) == [1000] * 4


def test_review_reconciliation_requires_completion_and_is_idempotent(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    started = job()
    key = run_key(config, started)
    uncertain = {"mapping": [0, 1, 2, 3], "auto_replenish": True}
    assert apply_history_job(store, config, started, fingerprint, uncertain, [10, 0, 0, 0]) == "review"
    with pytest.raises(ValueError, match="completed"):
        reconcile_completed_review(store, key, {"spool0": 4, "spool1": 6})
    assert apply_history_job(store, config, job(status="completed")) == "review"
    with pytest.raises(ValueError):
        reconcile_completed_review(store, key, {"spool0": 4, "spool1": float("nan")})
    assert remaining(store) == [1000] * 4
    assert reconcile_completed_review(store, key, {"spool0": 4, "spool1": 6}) is True
    assert reconcile_completed_review(store, key, {"spool0": 4, "spool1": 6}) is False
    with pytest.raises(ValueError, match="different amounts"):
        reconcile_completed_review(store, key, {"spool0": 5, "spool1": 6})
    assert remaining(store) == [996, 994, 1000, 1000]
    assert store.read()["runs"][key]["manual_consumption"] == {"spool0": 4, "spool1": 6}


def test_review_saves_scale_evidence_only_when_it_matches_confirmed_usage(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['plans'].clear())
    config = store.read()['printer']
    active = job()
    key = run_key(config, active)
    apply_history_job(store, config, active, fingerprint,
                      {'mapping':[0, 1, 2, 3], 'auto_replenish':True}, [10, 0, 0, 0])
    apply_history_job(store, config, job(status='completed'))
    with pytest.raises(ValueError, match='readings'):
        reconcile_completed_review(store, key, {'spool0': 4}, {'spool0': {'before_g': 950, 'after_g': 940}})
    assert remaining(store) == [1000] * 4
    readings = {'spool0': {'before_g': 950, 'after_g': 946}}
    assert reconcile_completed_review(store, key, {'spool0': 4}, readings)
    assert not reconcile_completed_review(store, key, {'spool0': 4}, readings)
    assert store.read()['runs'][key]['manual_measurements'] == readings
    assert remaining(store)[0] == 996


def test_review_of_cancelled_print_cannot_be_reconciled_as_completed(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    started = job()
    key = run_key(config, started)
    uncertain = {"mapping": [0, 1, 2, 3], "auto_replenish": True}
    assert apply_history_job(store, config, started, fingerprint, uncertain, [1, 0, 0, 0]) == "review"
    assert apply_history_job(store, config, job(status="cancelled")) == "review"
    with pytest.raises(ValueError, match="completed"):
        reconcile_completed_review(store, key, {"spool0": 1})


def test_replenishment_observation_is_kept_for_review_but_does_not_assign_amounts(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    started = job()
    initial = {"mapping": [0, 1, 2, 3], "auto_replenish": True, "replenished": [0, 1, 2, 3]}
    assert apply_history_job(store, config, started, fingerprint, initial, [10, 0, 0, 0]) == "review"
    switched = {"mapping": [1, 1, 2, 3], "auto_replenish": True, "replenished": [1, 1, 2, 3]}
    assert apply_history_job(store, config, started, fingerprint, switched) == "review"
    assert store.read()["runs"][run_key(config, started)]["replenishment_observed"] is True
    assert remaining(store) == [1000] * 4


def test_observed_print_tracks_remapped_physical_head(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["plans"].clear())
    config = store.read()["printer"]
    mapped = {"mapping": [1, 0, 2, 3], "auto_replenish": False}
    assert apply_history_job(store, config, job(), fingerprint, mapped, [4, 0, 0, 0]) == "active"
    assert apply_history_job(store, config, job(status="completed")) == "committed"
    assert remaining(store) == [1000, 996, 1000, 1000]


def test_simulated_motion_reconciliation_is_atomic_and_once(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['plans'].clear())
    def bind(db):
        for i, uid in enumerate(('01020304', '05060708')):
            db['spools'][f'spool{i}']['calibration'] = {'uid': uid, 'diameter_mm': 1.75, 'density_g_cm3': 1.24}
    store.update(bind)
    config = store.read()['printer']
    active = job()
    key = run_key(config, active)
    assert apply_history_job(store, config, active, fingerprint,
                             {'mapping': [0, 1, 2, 3], 'auto_replenish': True}, [1, 1, 0, 0]) == 'review'
    start = {'state':'active', 'valid':True, 'identity_verified':True, 'epoch':'e', 'capture_id':'capture',
             'filename':'job.gcode', 'started_at':1010, 'initial_tag_uids':['01020304', '05060708', None, None]}
    assert begin_motion_watch(store, key, start) is True
    end = {**start, 'state':'completed', 'finished_at':1100, 'head_mm':[100, 50, 0, 0], 'spool_insert_events':[False]*4,
           'final_tag_uids':list(start['initial_tag_uids'])}
    with pytest.raises(ValueError, match='completed'):
        commit_motion_watch(store, key, end)
    assert apply_history_job(store, config, job(status='completed')) == 'review'
    bad = {**end, 'spool_insert_events':[False, True, False, False]}
    with pytest.raises(ValueError, match='identity'):
        commit_motion_watch(store, key, bad)
    assert remaining(store) == [1000]*4
    assert commit_motion_watch(store, key, end) is True
    assert remaining(store) == [999.702, 999.851, 1000, 1000]
    assert commit_motion_watch(Store(store.directory), key, end) is False
    assert remaining(store) == [999.702, 999.851, 1000, 1000]


def test_prototype_identity_not_verified_cannot_start_automatic_watch(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['plans'].clear())
    config = store.read()['printer']
    active = job()
    key = run_key(config, active)
    apply_history_job(store, config, active, fingerprint,
                      {'mapping': [0, 1, 2, 3], 'auto_replenish': True}, [1, 0, 0, 0])
    assert not begin_motion_watch(store, key, {'state': 'active', 'valid': True, 'identity_verified': False})
    assert 'motion_watch' not in store.read()['runs'][key]


def test_opt_in_motion_monitor_books_simulated_verified_replenishment_once(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['plans'].clear())
    def configure(db):
        db['printer']['guard_mode'] = 'off'
        for i, uid in enumerate(('01020304', '05060708')):
            db['spools'][f'spool{i}']['calibration'] = {'uid': uid, 'diameter_mm': 1.75, 'density_g_cm3': 1.24}
    store.update(configure)
    phase = {'active': True}
    start = {'state':'active', 'valid':True, 'identity_verified':True, 'epoch':'e', 'capture_id':'capture',
             'filename':'job.gcode', 'started_at':1010, 'initial_tag_uids':['01020304', '05060708', None, None]}
    class Client:
        def __init__(self, host, port): pass
        def status(self):
            return {'state': 'printing' if phase['active'] else 'complete', 'filename':'job.gcode', 'klippy_state':'ready'}
        def history(self):
            return [job(status='in_progress' if phase['active'] else 'completed')]
        def mapping_snapshot(self, filename):
            return {'mapping':[0, 1, 2, 3], 'auto_replenish':True}
        def inspect_gcode(self, filename):
            return fingerprint[0], fingerprint[1], [1, 1, 0, 0]
        def motion_evidence(self):
            return start if phase['active'] else {**start, 'state':'completed', 'finished_at':1100,
                 'head_mm':[100, 50, 0, 0], 'spool_insert_events':[False]*4,
                 'final_tag_uids':list(start['initial_tag_uids'])}
    poll_once(store, Client, experimental_motion=True)
    assert remaining(store) == [1000] * 4
    phase['active'] = False
    poll_once(store, Client, experimental_motion=True)
    assert remaining(store) == [999.702, 999.851, 1000, 1000]
    poll_once(store, Client, experimental_motion=True)
    assert remaining(store) == [999.702, 999.851, 1000, 1000]


def test_opt_in_motion_monitor_handles_simulated_untagged_esun(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['plans'].clear())
    def configure(db):
        db['printer']['guard_mode'] = 'off'
        db['spools']['spool0']['calibration'] = {'uid':'01020304', 'diameter_mm':1.75, 'density_g_cm3':1.24}
        db['spools']['spool1']['calibration'] = {'uid':None, 'identity_mode':'manual_confirmed', 'diameter_mm':1.75, 'density_g_cm3':1.24}
    store.update(configure)
    phase = {'active': True}
    start = {'state':'active', 'valid':True, 'identity_verified':True, 'epoch':'e', 'capture_id':'manual-capture',
             'filename':'job.gcode', 'started_at':1010, 'initial_tag_uids':['01020304', None, None, None]}
    class Client:
        def __init__(self, host, port): pass
        def status(self): return {'state':'printing' if phase['active'] else 'complete', 'filename':'job.gcode', 'klippy_state':'ready'}
        def history(self): return [job(status='in_progress' if phase['active'] else 'completed')]
        def mapping_snapshot(self, filename): return {'mapping':[0, 1, 2, 3], 'auto_replenish':True}
        def inspect_gcode(self, filename): return fingerprint[0], fingerprint[1], [1, 1, 0, 0]
        def motion_evidence(self):
            return start if phase['active'] else {**start, 'state':'completed', 'finished_at':1100,
                 'head_mm':[100, 50, 0, 0], 'spool_insert_events':[False]*4,
                 'final_tag_uids':list(start['initial_tag_uids']),
                 'manual_continuity':[False, True, False, False]}
    poll_once(store, Client, experimental_motion=True)
    phase['active'] = False
    poll_once(store, Client, experimental_motion=True)
    assert remaining(store) == [999.702, 999.851, 1000, 1000]
    poll_once(store, Client, experimental_motion=True)
    assert remaining(store) == [999.702, 999.851, 1000, 1000]


@pytest.mark.parametrize("terminal", ["cancelled", "error", "klippy_shutdown", "klippy_disconnect", "interrupted"])
def test_failed_print_never_debits_planned_total(tmp_path, terminal):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint, IDENTITY) == "active"
    assert apply_history_job(store, config, job(status=terminal)) in ("cancelled", "error")
    assert remaining(store) == [1000] * 4
    assert apply_history_job(store, config, job(status="completed")) != "committed"
    assert remaining(store) == [1000] * 4


def test_restart_between_start_and_completion_requires_review(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint, IDENTITY) == "active"
    restarted = Store(store.directory)
    invalidate_active_runs(restarted, config)
    assert apply_history_job(restarted, config, job(status="completed")) == "review"
    assert remaining(store) == [1000] * 4


def test_two_distinct_real_prints_each_consume_once(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    for index in (1, 2):
        current = job(job_id=f"job-{index}", start=1010.0 + index)
        assert apply_history_job(store, config, current, fingerprint, IDENTITY) == "active"
        current["status"] = "completed"
        assert apply_history_job(store, config, current) == "committed"
    assert remaining(store) == [980, 960, 940, 920]


def test_unobserved_later_job_does_not_erase_prior_committed_plan(tmp_path):
    store, plan_id, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint, IDENTITY) == "active"
    assert apply_history_job(store, config, job(status="completed")) == "committed"
    assert apply_history_job(store, config, job(status="completed", job_id="later", start=1020), fingerprint) == "review"
    assert store.read()["plans"][plan_id]["status"] == "committed"
    assert remaining(store) == [990, 980, 970, 960]


def test_same_content_different_spool_mapping_requires_review(tmp_path):
    store, _, fingerprint, file = setup_plan(tmp_path)
    def change(db):
        db["spools"]["alternate"] = {"name": "Alternate", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "alternate"
    store.update(change)
    create_plan(store, file, "job.gcode", [10, 20, 30, 40], store.read(), now=1002.0)
    assert apply_history_job(store, store.read()["printer"], job(status="completed"), fingerprint) == "review"
    assert remaining(store) == [1000] * 4
    assert store.read()["spools"]["alternate"]["remaining_g"] == 1000


def test_reassignment_between_export_and_start_requires_review(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    def reassign(db):
        db["spools"]["replacement"] = {"name": "Replacement", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "replacement"
    store.update(reassign)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint, IDENTITY) == "review"
    assert store.read()["spools"]["spool0"]["remaining_g"] == 1000
    assert store.read()["spools"]["replacement"]["remaining_g"] == 1000


def test_unavailable_printer_preserves_inventory(tmp_path):
    store, _, _, _ = setup_plan(tmp_path)
    class Unavailable:
        def __init__(self, host, port): pass
        def status(self): raise MoonrakerError("offline")
    poll_once(store, Unavailable)
    assert remaining(store) == [1000] * 4
    assert store.read()["monitor"]["state"] == "disconnected"
    assert not store.read()["monitor"]["connected"]


def test_polling_history_uses_remote_identity(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db["printer"].update({"guard_mode": "off"}))
    phase = {"active": True}
    class FakeClient:
        def __init__(self, host, port):
            assert host == "U1.local" and port == 7125
        def status(self):
            return {"state": "printing" if phase["active"] else "complete", "filename": "job.gcode", "klippy_state": "ready"}
        def history(self):
            return [job(status="in_progress" if phase["active"] else "completed")]
        def mapping_snapshot(self, filename):
            return IDENTITY
        def fingerprint(self, filename):
            assert filename == "job.gcode"
            return fingerprint
    poll_once(store, FakeClient)
    assert remaining(store) == [1000] * 4
    phase["active"] = False
    poll_once(store, FakeClient)
    assert remaining(store) == [990, 980, 970, 960]
    poll_once(store, FakeClient)
    assert remaining(store) == [990, 980, 970, 960]
    assert store.read()["monitor"]["connected"]


def test_migrates_schema_one_without_inventory_loss(tmp_path):
    store = Store(tmp_path)
    old = {"schema_version": 1, "language": "en", "safety_margin_g": 0,
           "slots": {"1": "legacy", "2": "", "3": "", "4": ""},
           "spools": {"legacy": {"name": "Old", "material": "PLA", "remaining_g": 50}},
           "last_preflight": None}
    store.path.write_text(json.dumps(old))
    new = store.read()
    assert new["schema_version"] == SCHEMA_VERSION
    assert new["spools"]["legacy"]["remaining_g"] == 50
    assert new["printer"]["port"] == 7125


def test_stock_moonraker_response_shapes_and_file_hash():
    payload = b"; filament used [g] = 1, 2, 3, 4\n"
    class Opener:
        def __init__(self): self.paths = []
        def open(self, url, timeout):
            self.paths.append(url)
            if "/printer/objects/query?" in url:
                body = {"result": {"status": {"webhooks": {"state": "ready"},
                                               "print_stats": {"state": "printing", "filename": "folder/job.gcode"}}}}
            elif "/server/history/list?" in url:
                body = {"result": {"count": 1, "jobs": [job(filename="folder/job.gcode")]}}
            elif "/server/files/metadata?" in url:
                body = {"result": {"size": len(payload)}}
            else:
                return BytesIO(payload)
            return BytesIO(json.dumps(body).encode())
    opener = Opener()
    client = MoonrakerClient("U1.local", 7125, opener=opener)
    assert client.status()["state"] == "printing"
    assert client.history()[0]["job_id"] == "job-1"
    assert client.fingerprint("folder/job.gcode")[1] == len(payload)
    assert any("/server/files/gcodes/folder/job.gcode" in path for path in opener.paths)


def test_read_head_counters_does_not_invent_maintenance_status():
    class Opener:
        def open(self, url, timeout):
            assert '/printer/objects/query?' in url
            data = {'extruder': {'switch_count': 20, 'last_maintenance_count': 8, 'retry_count': 2, 'error_count': 1},
                    'extruder1': {'switch_count': 3, 'last_maintenance_count': 8},
                    'extruder2': {}, 'extruder3': {'switch_count': True, 'last_maintenance_count': 0}}
            return BytesIO(json.dumps({'result': {'status': data}}).encode())
    heads = MoonrakerClient('U1.local', 7125, opener=Opener()).head_maintenance()
    assert heads[0]['switches_since_maintenance'] == 12
    assert all(item['switches_since_maintenance'] is None for item in heads[1:])


@pytest.mark.parametrize("result", ["ok", {}])
def test_pause_accepts_both_documented_and_u1_empty_success_result(result):
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "POST"
            assert request.full_url.endswith("/printer/print/pause")
            return BytesIO(json.dumps({"result": result}).encode())
    MoonrakerClient("U1.local", 7125, opener=Opener()).pause()


def test_printer_monitor_supplies_same_job_profile_for_diagnostic_estimates(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    store.update(lambda db: db['printer'].update({'guard_mode': 'off'}))
    params = [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]
    class Client:
        def __init__(self, host, port): self.last_inspection_metadata = None
        def status(self): return {'state': 'printing', 'filename': 'job.gcode', 'klippy_state': 'ready'}
        def history(self): return [job()]
        def mapping_snapshot(self, filename): return {'mapping': [1, 0, 2, 3], 'auto_replenish': True}
        def inspect_gcode(self, filename):
            self.last_inspection_metadata = {'filament_parameters': params, 'filament_type': 'PLA;PLA;PLA;PLA'}
            return fingerprint[0], fingerprint[1], [10, 20, 0, 0]
    poll_once(store, Client)
    profile = store._motion_slicer_profile
    assert profile['filename'] == 'job.gcode' and profile['started_at'] == 1010
    assert profile['mapping'] == [1, 0, 2, 3] and profile['parameters'] == params
    assert remaining(store) == [1000] * 4
    assert next(iter(store.read()['runs'].values()))['status'] == 'review'


def test_selected_head_requires_matching_active_job():
    from moonraker import MoonrakerClient
    client = MoonrakerClient('example.local', 7125)
    status = {'toolhead': {'extruder': 'extruder2'},
              'print_stats': {'state': 'printing', 'filename': 'part.gcode'}}
    client._json = lambda path: {'status': status}
    assert client.active_head('part.gcode') == 2
    assert client.active_head('different.gcode') is None
    status['print_stats']['state'] = 'paused'
    assert client.active_head('part.gcode') is None
    status['print_stats']['state'] = 'printing'
    status['toolhead']['extruder'] = 'unknown'
    assert client.active_head('part.gcode') is None
