import json

import pytest

from backup import BACKUP_FORMAT, BACKUP_VERSION, create_backup, import_backup, parse_backup, write_backup
from spool_tracker import APP_VERSION, BackupBridge, HTML_PAGE, normalize_dialog_path
from storage import Store, StorageError


def populated(store):
    def change(db):
        db["language"] = "ru"
        db["safety_margin_g"] = 12.5
        db["spools"]["spool1"] = {"name": "Black", "material": "PLA", "remaining_g": 900}
        db["slots"]["1"] = "spool1"
        db["printer"] = {"host": "U1.local", "port": 7125, "enabled": True}
        db["monitor"] = {"connected": True, "state": "printing", "filename": "job.gcode", "error": "", "checked_at": 50}
        db["last_preflight"] = {"summary": "OK", "rows": [], "time": "today"}
        db["plans"]["p"] = {"filename": "job.gcode", "sha256": "a" * 64, "size": 123,
                            "weights": [10, 0, 0, 0], "spool_ids": ["spool1", "", "", ""],
                            "created_at": 5, "status": "committed", "printer": db["printer"].copy()}
        db["runs"]["r"] = {"job_id": "remote-job", "plan_id": "p", "start_time": 6,
                           "status": "committed", "filename": "job.gcode"}
    store.update(change)


def test_backup_round_trip_and_no_export_mutation(tmp_path):
    store = Store(tmp_path / "live")
    populated(store)
    before_bytes = store.path.read_bytes()
    target = tmp_path / "portable.json"
    write_backup(store, target, APP_VERSION)
    assert store.path.read_bytes() == before_bytes
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["backup_format"] == BACKUP_FORMAT
    assert raw["backup_version"] == BACKUP_VERSION
    assert raw["app_version"] == APP_VERSION
    assert "monitor" not in raw["data"]
    assert set(raw["data"]) == set(store.read()) - {"monitor"}
    old = store.read()
    other = Store(tmp_path / "restored")
    other.read()
    backup_path = import_backup(other, target)
    restored = other.read()
    for key in raw["data"]:
        assert restored[key] == old[key]
    assert restored["monitor"] == {"connected": False, "state": "disconnected", "filename": "", "error": "", "checked_at": 0}
    assert backup_path.exists()
    assert backup_path.name.startswith("pre-import-")
    assert json.loads(backup_path.read_text(encoding="utf-8"))["spools"] == {}


@pytest.mark.parametrize("change", [
    lambda d: d.update(backup_format="wrong"),
    lambda d: d.update(backup_version=99),
    lambda d: d["data"].pop("plans"),
    lambda d: d["data"]["spools"]["spool1"].update(remaining_g=-1),
    lambda d: d["data"]["slots"].update({"1": "missing"}),
])
def test_invalid_backup_does_not_touch_database(tmp_path, change):
    store = Store(tmp_path / "live")
    populated(store)
    before = store.path.read_bytes()
    document = create_backup(store, APP_VERSION)
    change(document)
    target = tmp_path / "bad.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StorageError):
        import_backup(store, target)
    assert store.path.read_bytes() == before
    assert not (store.directory / "backups").exists()


def test_invalid_json_and_oversized_backup_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError, match="Invalid backup JSON"):
        parse_backup(path)
    path.write_bytes(b" " * (10 * 1024 * 1024 + 1))
    with pytest.raises(StorageError, match="maximum file size"):
        parse_backup(path)


def test_atomic_import_failure_keeps_old_database_and_safety_copy(tmp_path, monkeypatch):
    store = Store(tmp_path / "live")
    populated(store)
    before = store.path.read_bytes()
    replacement = Store(tmp_path / "new")
    replacement.read()
    document = create_backup(replacement, APP_VERSION)
    source = tmp_path / "restore.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(store, "_atomic_write", lambda data: (_ for _ in ()).throw(OSError("simulated failure")))
    with pytest.raises(OSError, match="simulated failure"):
        import_backup(store, source)
    assert store.path.read_bytes() == before
    backups = list((store.directory / "backups").glob("pre-import-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == json.loads(before)


@pytest.mark.parametrize("wrap", [lambda path: path, lambda path: [path], lambda path: (path,), lambda path: ["", path]])
def test_native_bridge_uses_whole_save_and_open_paths(tmp_path, wrap):
    store = Store(tmp_path / "live")
    populated(store)
    path = tmp_path / "portable.json"
    results = [wrap(str(path)), wrap(str(path))]
    calls = []
    class Window:
        def create_file_dialog(self, *args, **kwargs):
            calls.append((args, kwargs))
            return results.pop(0)
    class FileDialog:
        SAVE = 20
        OPEN = 10
    bridge = BackupBridge(store, type("Webview", (), {"FileDialog": FileDialog}))
    bridge.window = Window()
    exported = bridge.export_backup()
    assert exported == {"status": "ok", "path": str(path)}
    assert path.is_file()  # A string path must never be reduced to its first character, '/'.
    assert bridge.import_backup()["status"] == "ok"
    assert [call[0][0] for call in calls] == [20, 10]
    assert "pywebviewready" in HTML_PAGE
    assert "backupUnavailable" in HTML_PAGE


@pytest.mark.parametrize("result", [None, "", [], (), [""], ("",), [None, ""]])
def test_native_bridge_cancelled_dialogs(tmp_path, result):
    store = Store(tmp_path / "live")
    store.read()
    class Window:
        def create_file_dialog(self, *args, **kwargs):
            return result
    class FileDialog:
        SAVE = 20
        OPEN = 10
    bridge = BackupBridge(store, type("Webview", (), {"FileDialog": FileDialog}))
    bridge.window = Window()
    assert bridge.export_backup() == {"status": "cancelled"}
    assert bridge.import_backup() == {"status": "cancelled"}
    assert not (store.directory / "backups").exists()


def test_normalize_dialog_path_accepts_pathlike_and_rejects_other_values(tmp_path):
    path = tmp_path / "Desktop" / "file.json"
    assert normalize_dialog_path(path) == str(path)
    assert normalize_dialog_path(str(path)) == str(path)
    assert normalize_dialog_path([None, "", path]) == str(path)
    assert normalize_dialog_path(42) is None
    assert normalize_dialog_path([42, b"/tmp/bytes", ""]) is None


def test_export_requires_portable_location(tmp_path):
    store = Store(tmp_path / "live")
    store.read()
    with pytest.raises(StorageError, match="outside"):
        write_backup(store, store.directory / "my-backup.json", APP_VERSION)
    with pytest.raises(StorageError, match="filesystem root"):
        write_backup(store, tmp_path.anchor, APP_VERSION)
