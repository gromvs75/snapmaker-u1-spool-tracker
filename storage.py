"""Persistent, process-safe inventory storage."""

import copy
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from filelock import FileLock, Timeout

SCHEMA_VERSION = 2
APP_NAME = "SnapmakerSpoolTracker"
LOGGER = logging.getLogger("snapmaker_tracker")


class StorageError(Exception):
    pass


class ValidationError(ValueError):
    pass


def data_directory(platform=None, home=None, environ=None):
    platform = platform or sys.platform
    home = Path(home) if home is not None else Path.home()
    environ = environ if environ is not None else os.environ
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if platform == "win32":
        return Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / APP_NAME
    return Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / APP_NAME


def empty_db():
    return {"schema_version": SCHEMA_VERSION, "language": "en", "safety_margin_g": 0.0,
            "slots": {str(i): "" for i in range(1, 5)}, "spools": {}, "last_preflight": None,
            "printer": {"host": "U1.local", "port": 7125, "enabled": False},
            "monitor": {"connected": False, "state": "disabled", "filename": "", "error": "", "checked_at": 0.0},
            "plans": {}, "runs": {}}


def printer_config(value):
    if not isinstance(value, dict):
        raise ValidationError("Printer configuration must be an object")
    host = value.get("host")
    port = value.get("port")
    enabled = value.get("enabled")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}", host):
        raise ValidationError("Enter a hostname or IPv4 address without a URL scheme")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValidationError("Port must be between 1 and 65535")
    if not isinstance(enabled, bool):
        raise ValidationError("Enabled must be true or false")
    return {"host": host, "port": port, "enabled": enabled}


def _validated_jobs(data, result):
    plans, runs = data.get("plans", {}), data.get("runs", {})
    if not isinstance(plans, dict) or not isinstance(runs, dict):
        raise StorageError("Invalid job ledger")
    for plan_id, plan in plans.items():
        if not isinstance(plan_id, str) or not isinstance(plan, dict):
            raise StorageError("Invalid planned job")
        filename = plan.get("filename")
        sha = plan.get("sha256")
        size = plan.get("size")
        weights = plan.get("weights")
        spool_ids = plan.get("spool_ids")
        if (not isinstance(filename, str) or not filename or len(filename) > 1024
                or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
                or isinstance(size, bool) or not isinstance(size, int) or size < 0
                or not isinstance(weights, list) or len(weights) != 4
                or not isinstance(spool_ids, list) or len(spool_ids) != 4
                or any(not isinstance(value, str) for value in spool_ids)
                or plan.get("status") not in ("planned", "active", "committed", "cancelled", "error", "review")):
            raise StorageError("Invalid planned job")
        result["plans"][plan_id] = {
            "filename": filename, "sha256": sha, "size": size,
            "weights": [weight(value) for value in weights], "spool_ids": spool_ids,
            "created_at": weight(plan.get("created_at")), "status": plan["status"],
            "printer": printer_config(plan.get("printer")),
        }
    for run_id, run in runs.items():
        if (not isinstance(run_id, str) or not isinstance(run, dict)
                or not isinstance(run.get("job_id"), str)
                or run.get("plan_id") not in result["plans"]
                or run.get("status") not in ("active", "committed", "cancelled", "error", "review")):
            raise StorageError("Invalid job run")
        result["runs"][run_id] = {
            "job_id": run["job_id"], "plan_id": run["plan_id"],
            "start_time": weight(run.get("start_time")), "status": run["status"],
            "filename": str(run.get("filename", ""))[:1024],
        }


def weight(value):
    if isinstance(value, bool) or value is None:
        raise ValidationError("Weight must be a finite non-negative number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError("Weight must be a finite non-negative number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValidationError("Weight must be a finite non-negative number")
    return result


def label(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must not be empty")
    if len(value.strip()) > 200:
        raise ValidationError(f"{field} is too long")
    return value.strip()


def validate_db(data):
    if not isinstance(data, dict):
        raise StorageError("Database root must be an object")
    version = data.get("schema_version", 0)
    if version not in (0, 1, SCHEMA_VERSION):
        raise StorageError(f"Unsupported database schema version: {version}")
    result = empty_db()
    language = data.get("language", "en")
    if language not in ("en", "ru", "de", "uk", "es"):
        raise StorageError("Invalid database language")
    result["language"] = language
    try:
        result["printer"] = printer_config(data.get("printer", result["printer"]))
    except ValidationError as exc:
        raise StorageError(f"Invalid printer configuration: {exc}") from exc
    monitor = data.get("monitor", result["monitor"])
    if (not isinstance(monitor, dict) or not isinstance(monitor.get("connected"), bool)
            or not isinstance(monitor.get("state"), str) or not isinstance(monitor.get("filename"), str)
            or not isinstance(monitor.get("error"), str)):
        raise StorageError("Invalid monitor status")
    result["monitor"] = {"connected": monitor["connected"], "state": monitor["state"][:100],
                         "filename": monitor["filename"][:1024], "error": monitor["error"][:500],
                         "checked_at": weight(monitor.get("checked_at", 0))}
    last = data.get("last_preflight")
    if last is not None:
        if not isinstance(last, dict) or not isinstance(last.get("summary"), str) or len(last["summary"]) > 500 or not isinstance(last.get("rows"), list) or len(last["rows"]) not in (0, 4):
            raise StorageError("Invalid preflight result")
        result["last_preflight"] = last
    try:
        result["safety_margin_g"] = weight(data.get("safety_margin_g", 0))
        spools = data["spools"]
        slots = data["slots"]
        if not isinstance(spools, dict) or not isinstance(slots, dict):
            raise StorageError("Invalid database inventory")
        for spool_id, spool in spools.items():
            if not isinstance(spool_id, str) or not spool_id or not isinstance(spool, dict):
                raise StorageError("Invalid spool record")
            result["spools"][spool_id] = {
                "name": label(spool.get("name"), "Name"),
                "material": label(spool.get("material"), "Material"),
                "remaining_g": weight(spool.get("remaining_g")),
            }
        for slot in result["slots"]:
            assigned = slots.get(slot, "")
            if assigned not in result["spools"] and assigned != "":
                raise StorageError(f"Slot {slot} refers to a missing spool")
            result["slots"][slot] = assigned
        _validated_jobs(data, result)
    except (KeyError, ValidationError, TypeError) as exc:
        raise StorageError(f"Invalid database: {exc}") from exc
    return result


class Store:
    def __init__(self, directory=None, legacy_paths=()):
        self.directory = Path(directory) if directory is not None else data_directory()
        self.path = self.directory / "spools_u1.json"
        self.lock_path = self.directory / "spools_u1.lock"
        self.lock = FileLock(str(self.lock_path), timeout=30)
        self.legacy_paths = [Path(p) for p in legacy_paths]

    def _atomic_write(self, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".spools-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            if os.name != "nt":
                dir_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _backup_bad(self, cause):
        backup_dir = self.directory / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = backup_dir / f"spools_u1.corrupt-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
        shutil.copy2(self.path, destination)
        LOGGER.error("Database invalid; original preserved at %s, backup at %s: %s", self.path, destination, cause)
        raise StorageError(f"Database cannot be read ({cause}). Original preserved at {self.path}; backup: {destination}")

    def _read_locked(self):
        if not self.path.exists():
            for legacy in self.legacy_paths:
                if legacy.exists() and legacy.resolve() != self.path.resolve():
                    try:
                        with open(legacy, encoding="utf-8") as handle:
                            migrated = validate_db(json.load(handle))
                    except (OSError, ValueError, StorageError) as exc:
                        raise StorageError(f"Legacy database at {legacy} is invalid; it was not modified: {exc}") from exc
                    self._atomic_write(migrated)
                    LOGGER.info("Migrated legacy database from %s to %s", legacy, self.path)
                    return migrated
            fresh = empty_db()
            self._atomic_write(fresh)
            return fresh
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
            data = validate_db(raw)
        except (OSError, ValueError, StorageError) as exc:
            self._backup_bad(exc)
        if raw != data:
            self._atomic_write(data)
        return data

    def read(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock:
                return copy.deepcopy(self._read_locked())
        except Timeout as exc:
            raise StorageError("Timed out waiting for the database lock") from exc

    def update(self, change):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock:
                data = self._read_locked()
                result = change(data)
                validated = validate_db(data)
                self._atomic_write(validated)
                return result
        except Timeout as exc:
            raise StorageError("Timed out waiting for the database lock") from exc

    def export_snapshot(self):
        """Read a validated durable snapshot without rewriting the database."""
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock:
                if not self.path.exists():
                    return empty_db()
                with open(self.path, encoding="utf-8") as handle:
                    return validate_db(json.load(handle))
        except Timeout as exc:
            raise StorageError("Timed out waiting for the database lock") from exc
        except (OSError, ValueError) as exc:
            raise StorageError(f"Database cannot be exported: {exc}") from exc

    def replace_snapshot(self, snapshot):
        """Save the old database, then atomically replace it under one lock."""
        validated = validate_db(snapshot)
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock:
                old = self._read_locked()
                backup_dir = self.directory / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                name = f"pre-import-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
                destination = backup_dir / name
                with open(destination, "x", encoding="utf-8") as handle:
                    json.dump(old, handle, indent=2, ensure_ascii=False, allow_nan=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._atomic_write(validated)
                return destination
        except Timeout as exc:
            raise StorageError("Timed out waiting for the database lock") from exc


def legacy_paths():
    paths = [Path(__file__).resolve().parent / "spools_u1.json",
             Path(sys.executable).resolve().parent / "spools_u1.json"]
    if getattr(sys, "_MEIPASS", None):
        paths.append(Path(sys._MEIPASS) / "spools_u1.json")
    return list(dict.fromkeys(paths))
