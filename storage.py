"""Persistent, process-safe inventory storage."""

import copy
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
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
            "slots": {str(i): "" for i in range(1, 5)}, "spools": {}, "last_preflight": None}


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
    if version not in (0, SCHEMA_VERSION):
        raise StorageError(f"Unsupported database schema version: {version}")
    result = empty_db()
    language = data.get("language", "en")
    if language not in ("en", "ru", "de", "uk", "es"):
        raise StorageError("Invalid database language")
    result["language"] = language
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
    except (KeyError, ValidationError, TypeError) as exc:
        raise StorageError(f"Invalid database: {exc}") from exc
    return result


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Store:
    def __init__(self, directory=None, legacy_paths=()):
        self.directory = Path(directory) if directory is not None else data_directory()
        self.path = self.directory / "spools_u1.json"
        self.lock_path = self.directory / "spools_u1.lock"
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
        with _lock(self.lock_path):
            return copy.deepcopy(self._read_locked())

    def update(self, change):
        with _lock(self.lock_path):
            data = self._read_locked()
            result = change(data)
            validated = validate_db(data)
            self._atomic_write(validated)
            return result


def legacy_paths():
    paths = [Path(__file__).resolve().parent / "spools_u1.json",
             Path(sys.executable).resolve().parent / "spools_u1.json"]
    if getattr(sys, "_MEIPASS", None):
        paths.append(Path(sys._MEIPASS) / "spools_u1.json")
    return list(dict.fromkeys(paths))
