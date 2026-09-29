"""Portable, versioned inventory backups."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from storage import StorageError, empty_db, validate_db

BACKUP_FORMAT = "SnapmakerSpoolTracker"
BACKUP_VERSION = 1
MAX_BACKUP_BYTES = 10 * 1024 * 1024
DURABLE_KEYS = frozenset(empty_db()) - {"monitor"}


def _reject_non_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def create_backup(store, app_version):
    snapshot = store.export_snapshot()
    return {
        "backup_format": BACKUP_FORMAT,
        "backup_version": BACKUP_VERSION,
        "app_version": app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": {key: snapshot[key] for key in DURABLE_KEYS},
    }


def write_backup(store, path, app_version):
    target = Path(path).expanduser().resolve()
    if target == Path(target.anchor):
        raise StorageError("Choose a backup file, not the filesystem root")
    if target == store.directory.resolve() or store.directory.resolve() in target.parents:
        raise StorageError("Choose a backup location outside the application data directory")
    document = create_backup(store, app_version)
    payload = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_BACKUP_BYTES:
        raise StorageError("Backup exceeds the maximum file size")
    fd, temp = tempfile.mkstemp(prefix=".snapmaker-backup-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target


def parse_backup(path):
    source = Path(path)
    try:
        with open(source, "rb") as handle:
            raw = handle.read(MAX_BACKUP_BYTES + 1)
    except OSError as exc:
        raise StorageError(f"Cannot read backup: {exc}") from exc
    if len(raw) > MAX_BACKUP_BYTES:
        raise StorageError("Backup exceeds the maximum file size")
    try:
        document = json.loads(raw.decode("utf-8"), parse_constant=_reject_non_json_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise StorageError(f"Invalid backup JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("backup_format") != BACKUP_FORMAT:
        raise StorageError("This is not a Snapmaker Spool Tracker backup")
    if type(document.get("backup_version")) is not int or document["backup_version"] != BACKUP_VERSION:
        raise StorageError("Unsupported backup version")
    if not isinstance(document.get("app_version"), str) or not isinstance(document.get("exported_at"), str):
        raise StorageError("Incomplete backup metadata")
    data = document.get("data")
    if not isinstance(data, dict) or set(data) != DURABLE_KEYS:
        raise StorageError("Incomplete or unexpected backup data")
    if data.get("schema_version") != empty_db()["schema_version"]:
        raise StorageError("Unsupported database schema in backup")
    restored = validate_db(data)
    restored["monitor"]["state"] = "disconnected" if restored["printer"]["enabled"] else "disabled"
    return restored


def import_backup(store, path):
    return store.replace_snapshot(parse_backup(path))
