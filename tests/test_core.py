import json
import multiprocessing
import os
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

from gcode import GCodeError, parse_u1_gcode
from preflight import check, has_problem
from storage import SCHEMA_VERSION, Store, StorageError, ValidationError, data_directory, empty_db, weight
import spool_tracker


def _process_add(directory, index):
    store = Store(directory)
    store.update(lambda db: db["spools"].update({str(index): {"name": str(index), "material": "PLA", "remaining_g": 1}}))


def gcode(tmp_path, metadata, prefix=b""):
    path = tmp_path / "job.gcode"
    path.write_bytes(prefix + metadata.encode())
    return path


@pytest.mark.parametrize("line,expected", [
    ("; filament used [g] = 12", [12, 0, 0, 0]),
    ("; filament used [g] = 12, 15", [12, 15, 0, 0]),
    ("; filament used [g] = 1, 2, 3, 4", [1, 2, 3, 4]),
    (" ;  Filament   Used [g]  =  0 , 0, 0, 0  ", [0, 0, 0, 0]),
])
def test_parse_variants(tmp_path, line, expected):
    assert parse_u1_gcode(gcode(tmp_path, line)) == expected


def test_total_is_not_per_tool(tmp_path):
    path = gcode(tmp_path, "; filament used [g] = 3, 4\n; total filament used [g] = 7")
    assert parse_u1_gcode(path) == [3, 4, 0, 0]
    with pytest.raises(GCodeError):
        parse_u1_gcode(gcode(tmp_path, "; total filament used [g] = 7"))


@pytest.mark.parametrize("metadata", ["", "; filament used [g] = ", "; filament used [g] = 1,", "; filament used [g] = nan", "; filament used [g] = inf", "; filament used [g] = -1", "; filament used [g] = 1,2,3,4,5"])
def test_bad_metadata_fails_closed(tmp_path, metadata):
    with pytest.raises(GCodeError):
        parse_u1_gcode(gcode(tmp_path, metadata))


def test_large_file_tail_and_fallback(tmp_path):
    prefix = b"G1 X1 Y2\n" * 500_000
    assert parse_u1_gcode(gcode(tmp_path, "; filament used [g] = 8", prefix), tail_bytes=2048) == [8, 0, 0, 0]
    assert parse_u1_gcode(gcode(tmp_path, "; filament used [g] = 9\n" + "G1 X1\n" * 400_000), tail_bytes=2048) == [9, 0, 0, 0]


def test_preflight_statuses():
    db = empty_db()
    db["spools"] = {"a": {"name": "PLA", "material": "PLA", "remaining_g": 100},
                    "b": {"name": "PETG", "material": "PETG", "remaining_g": 20}}
    db["slots"] = {"1": "a", "2": "b", "3": "", "4": ""}
    assert [r["status"] for r in check([100, 21, 2, 0], db)] == ["ok", "insufficient", "unassigned", "unused"]
    assert has_problem(check([100, 21, 2, 0], db))
    db["safety_margin_g"] = 1
    assert check([100, 0, 0, 0], db)[0]["status"] == "insufficient"
    assert not has_problem(check([0, 0, 0, 0], db))


def test_fresh_migration_and_unique_ids(tmp_path):
    store = Store(tmp_path / "new")
    assert store.read()["spools"] == {}
    assert set(store.read()["slots"].values()) == {""}
    assert store.read()["schema_version"] == SCHEMA_VERSION
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"language": "ru", "slots": {"1": "old", "2": "", "3": "", "4": ""}, "spools": {"old": {"name": "Old", "material": "PLA", "remaining_g": 10}}}))
    migrated = Store(tmp_path / "migrated", [legacy])
    assert migrated.read()["spools"]["old"]["remaining_g"] == 10
    assert migrated.read()["slots"]["1"] == "old"
    assert migrated.read()["schema_version"] == SCHEMA_VERSION
    assert legacy.exists()
    migrated.update(lambda db: db["spools"].update({"new": {"name": "New", "material": "PETG", "remaining_g": 1}}))
    assert "new" in migrated.read()["spools"]


def test_bad_weight_and_corruption_backup(tmp_path):
    store = Store(tmp_path)
    original = store.read()
    for invalid in [None, -1, "bad", float("nan"), float("inf"), True]:
        with pytest.raises(ValidationError):
            weight(invalid)
    store.path.write_text("{broken")
    with pytest.raises(StorageError, match="backup"):
        store.read()
    assert store.path.read_text() == "{broken"
    assert len(list((tmp_path / "backups").glob("*.json"))) == 1


def test_atomic_write_and_concurrent_updates(tmp_path):
    store = Store(tmp_path)
    store.read()
    def add(index):
        store.update(lambda db: db["spools"].update({str(index): {"name": str(index), "material": "PLA", "remaining_g": 1}}))
    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(store.read()["spools"]) == 20
    assert not list(tmp_path.glob(".spools-*.tmp"))
    assert json.loads(store.path.read_text())["schema_version"] == SCHEMA_VERSION


def test_cross_process_updates(tmp_path):
    store = Store(tmp_path)
    store.read()
    processes = [multiprocessing.Process(target=_process_add, args=(str(tmp_path), i)) for i in range(8)]
    for process in processes: process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert len(store.read()["spools"]) == 8


def test_platform_paths(tmp_path):
    assert data_directory("darwin", tmp_path) == tmp_path / "Library/Application Support/SnapmakerSpoolTracker"
    assert data_directory("win32", tmp_path, {"LOCALAPPDATA": "C:/Users/test/AppData/Local"}) == Path("C:/Users/test/AppData/Local/SnapmakerSpoolTracker")
    assert data_directory("win32", tmp_path, {}) == tmp_path / "AppData/Local/SnapmakerSpoolTracker"


def test_repeated_export_does_not_consume(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.read()
    def seed(db):
        db["spools"]["one"] = {"name": "PLA", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "one"
    store.update(seed)
    monkeypatch.setattr(spool_tracker, "STORE", store)
    path = gcode(tmp_path, "; filament used [g] = 200")
    for _ in range(5):
        assert spool_tracker.handle_slicer_hook(path) == 0
    assert store.read()["spools"]["one"]["remaining_g"] == 1000
    assert len(store.read()["plans"]) == 5
    assert {plan["status"] for plan in store.read()["plans"].values()} == {"planned"}
    assert store.read()["last_preflight"]["rows"][0]["status"] == "ok"


def test_failure_and_override(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.read()
    monkeypatch.setattr(spool_tracker, "STORE", store)
    path = gcode(tmp_path, "; filament used [g] = 200")
    monkeypatch.setattr(spool_tracker, "show_dialog", lambda *a, **kw: False)
    assert spool_tracker.handle_slicer_hook(path) == 1
    assert store.read()["plans"] == {}
    monkeypatch.setattr(spool_tracker, "show_dialog", lambda *a, **kw: True)
    assert spool_tracker.handle_slicer_hook(path) == 0
    assert len(store.read()["plans"]) == 1
    assert store.read()["last_preflight"]["rows"][0]["status"] == "unassigned"
    assert spool_tracker.handle_slicer_hook(gcode(tmp_path, "G1 X1")) == 1
    assert "parse failure" in store.read()["last_preflight"]["summary"]


def test_native_dialog_decisions(monkeypatch):
    monkeypatch.setattr(spool_tracker.sys, "platform", "win32")
    monkeypatch.setattr(spool_tracker, "_windows_dialog", lambda title, message, buttons: buttons[0])
    assert not spool_tracker.show_dialog("shortage", "ru", allow_proceed=True)
    monkeypatch.setattr(spool_tracker, "_windows_dialog", lambda title, message, buttons: buttons[1])
    assert spool_tracker.show_dialog("shortage", "ru", allow_proceed=True)
    monkeypatch.setattr(spool_tracker, "_windows_dialog", lambda *args: (_ for _ in ()).throw(RuntimeError("dialog failed")))
    assert not spool_tracker.show_dialog("shortage", "ru", allow_proceed=True)


def test_macos_tray_refresh_runs_on_main_thread(monkeypatch):
    queued = []
    pyobjc = ModuleType("PyObjCTools")
    pyobjc.AppHelper = ModuleType("AppHelper")
    pyobjc.AppHelper.callAfter = lambda callback: queued.append(callback)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc)
    monkeypatch.setattr(spool_tracker.sys, "platform", "darwin")
    app = spool_tracker.TrayApp()
    class Icon:
        menu = None
    app.icon = Icon()
    monkeypatch.setattr(app, "build_menu", lambda: "updated menu")
    worker = threading.Thread(target=app._schedule_menu_refresh)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert app.icon.menu is None
    assert len(queued) == 1
    queued[0]()
    assert app.icon.menu == "updated menu"


def test_api_validation_and_slot_cleanup(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    store = Store(tmp_path)
    class Handler(spool_tracker.WebHandler):
        pass
    Handler.store = store
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    def post(path, payload, headers=None):
        request = Request(base + path, data=json.dumps(payload).encode(),
                          headers={"Host": "127.0.0.1:8765", "Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)
    try:
        for bad in [None, -1, "nope", float("nan"), float("inf")]:
            code, result = post("/api/spools/add", {"name": "PLA", "material": "PLA", "remaining_g": bad})
            assert code == 400 and "error" in result
        code, result = post("/api/spools/add", {"name": "<script>alert(1)</script>", "material": "PLA", "remaining_g": 100})
        assert code == 200
        spool_id = result["result"]
        assert spool_id.startswith("spool_")
        code, _ = post("/api/slots", {"1": spool_id, "2": "", "3": "", "4": ""})
        assert code == 200
        code, _ = post("/api/slots", {"1": "missing", "2": "", "3": "", "4": ""})
        assert code == 400
        code, _ = post("/api/spools/delete", {"id": spool_id})
        assert code == 200
        assert store.read()["slots"]["1"] == ""
        assert not store.read()["spools"]
        code, result = post("/api/spools/add", {"name": "New", "material": "PLA", "remaining_g": 10})
        assert code == 200 and result["result"] != spool_id
        code, _ = post("/api/lang", {"language": "ru"}, {"Origin": "http://evil.example"})
        assert code == 403 and store.read()["language"] == "en"
        code, _ = post("/api/settings", {"safety_margin_g": 2}, {"Content-Type": "text/plain"})
        assert code == 415
        code, _ = post("/api/printer/config", {"host": "http://bad", "port": 7125, "enabled": True})
        assert code == 400
        code, _ = post("/api/printer/config", {"host": "U1.local", "port": 7125, "enabled": True})
        assert code == 200 and store.read()["printer"]["enabled"]
        class FakeMoonraker:
            def __init__(self, host, port):
                assert host == "U1.local" and port == 7125
            def status(self):
                return {"connected": True, "state": "standby", "filename": "", "klippy_state": "ready"}
        monkeypatch.setattr(spool_tracker, "MoonrakerClient", FakeMoonraker)
        code, result = post("/api/printer/test", {"host": "U1.local", "port": 7125})
        assert code == 200 and result["result"]["state"] == "standby"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
