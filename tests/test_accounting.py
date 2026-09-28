import json
import time
from io import BytesIO

import pytest

from accounting import apply_history_job, create_plan, fingerprint_file, run_key
from moonraker import MoonrakerClient, MoonrakerError, poll_once
from storage import Store


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
    assert apply_history_job(store, config, started, fingerprint) == "active"
    key = run_key(config, started)
    assert store.read()["runs"][key]["status"] == "active"
    assert remaining(store) == [1000] * 4
    completed = job(status="completed")
    assert apply_history_job(store, config, completed) == "committed"
    assert remaining(store) == [990, 980, 970, 960]
    assert store.read()["plans"][plan_id]["status"] == "committed"
    assert apply_history_job(store, config, completed) == "committed"
    assert remaining(store) == [990, 980, 970, 960]


@pytest.mark.parametrize("terminal", ["cancelled", "error", "klippy_shutdown", "klippy_disconnect", "interrupted"])
def test_failed_print_never_debits_planned_total(tmp_path, terminal):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint) == "active"
    assert apply_history_job(store, config, job(status=terminal)) in ("cancelled", "error")
    assert remaining(store) == [1000] * 4
    assert apply_history_job(store, config, job(status="completed")) != "committed"
    assert remaining(store) == [1000] * 4


def test_restart_between_start_and_completion(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(), fingerprint) == "active"
    restarted = Store(store.directory)
    assert apply_history_job(restarted, config, job(status="completed")) == "committed"
    assert apply_history_job(Store(store.directory), config, job(status="completed")) == "committed"
    assert remaining(store) == [990, 980, 970, 960]


def test_two_distinct_real_prints_each_consume_once(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    config = store.read()["printer"]
    for index in (1, 2):
        current = job(job_id=f"job-{index}", start=1010.0 + index)
        assert apply_history_job(store, config, current, fingerprint) == "active"
        current["status"] = "completed"
        assert apply_history_job(store, config, current) == "committed"
    assert remaining(store) == [980, 960, 940, 920]


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


def test_debit_uses_spool_ids_captured_at_preflight(tmp_path):
    store, _, fingerprint, _ = setup_plan(tmp_path)
    def reassign(db):
        db["spools"]["replacement"] = {"name": "Replacement", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "replacement"
    store.update(reassign)
    config = store.read()["printer"]
    assert apply_history_job(store, config, job(status="completed"), fingerprint) == "committed"
    assert store.read()["spools"]["spool0"]["remaining_g"] == 990
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
    class FakeClient:
        def __init__(self, host, port):
            assert host == "U1.local" and port == 7125
        def status(self):
            return {"state": "complete", "filename": "job.gcode", "klippy_state": "ready"}
        def history(self):
            return [job(status="completed")]
        def fingerprint(self, filename):
            assert filename == "job.gcode"
            return fingerprint
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
    assert new["schema_version"] == 2
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
