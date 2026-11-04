"""Read-only client and polling monitor for stock U1 Moonraker."""
import hashlib
import json
import logging
import math
import tempfile
import threading
import time
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from accounting import apply_history_job, begin_motion_watch, commit_motion_watch, file_name, invalidate_active_runs, run_key
from gcode import GCodeError, parse_u1_gcode_handle, parse_filament_parameters_handle
from material_guard import compare_materials
from spool_identity import read_tag_uids
from preflight import check, has_problem
from tool_mapping import MappingError, physical_weights, validate_mapping

LOGGER = logging.getLogger("snapmaker_tracker")
MAX_INSPECT_BYTES = 512 * 1024 * 1024


class MoonrakerError(Exception):
    pass


class MoonrakerClient:
    def __init__(self, host, port, timeout=5, opener=None, control_timeout=60):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
        self.control_timeout = control_timeout
        self.opener = opener or build_opener(ProxyHandler({}))

    def _open(self, path):
        try:
            return self.opener.open(self.base + path, timeout=self.timeout)
        except Exception as exc:
            raise MoonrakerError(str(exc)) from exc

    def _json(self, path):
        with self._open(path) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise MoonrakerError("Moonraker response is too large")
        try:
            data = json.loads(raw)
            if "error" in data:
                raise MoonrakerError(str(data["error"]))
            return data["result"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MoonrakerError("Invalid Moonraker response") from exc

    def _print_action(self, action):
        request = Request(self.base + "/printer/print/" + action, data=b"", method="POST")
        try:
            with self.opener.open(request, timeout=self.control_timeout) as response:
                raw = response.read(1_000_001)
        except Exception as exc:
            raise MoonrakerError(f"{action.capitalize()} request failed: {exc}") from exc
        if len(raw) > 1_000_000:
            raise MoonrakerError(f"Moonraker {action} response is too large")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise MoonrakerError(f"Invalid Moonraker {action} response") from exc
        # Snapmaker's Klipper webhook can return an empty result object; upstream
        # Moonraker commonly returns "ok". In both cases verify printer state separately.
        if not isinstance(data, dict) or data.get("result") not in ("ok", {}):
            raise MoonrakerError(f"Moonraker did not confirm {action}")

    def pause(self):
        self._print_action("pause")

    def resume(self):
        self._print_action("resume")

    def cancel(self):
        self._print_action("cancel")

    def status(self):
        result = self._json("/printer/objects/query?webhooks&print_stats")
        try:
            objects = result["status"]
            return {"connected": True, "state": objects["print_stats"]["state"],
                    "filename": objects["print_stats"].get("filename", ""),
                    "klippy_state": objects["webhooks"]["state"]}
        except (KeyError, TypeError) as exc:
            raise MoonrakerError("Moonraker print_stats/webhooks are unavailable") from exc

    def active_head(self, filename):
        """Read the selected physical extruder together with the current print state."""
        result = self._json('/printer/objects/query?toolhead&print_stats')
        try:
            status = result['status']
            stats = status['print_stats']
            if stats.get('state') != 'printing' or stats.get('filename') != filename:
                return None
            extruder = status['toolhead'].get('extruder')
            return {'extruder': 0, 'extruder1': 1, 'extruder2': 2, 'extruder3': 3}.get(extruder)
        except (KeyError, TypeError, AttributeError):
            return None

    def head_maintenance(self):
        """Read firmware counters, without predicting maintenance intervals."""
        result = self._json('/printer/objects/query?extruder&extruder1&extruder2&extruder3')
        try:
            objects = result['status']
            heads = []
            for index in range(4):
                item = objects['extruder' if index == 0 else f'extruder{index}']
                row = {'head': index}
                for key in ('switch_count', 'last_maintenance_count', 'retry_count', 'error_count'):
                    value = item.get(key)
                    row[key] = value if type(value) is int and value >= 0 else None
                if (row['switch_count'] is not None and row['last_maintenance_count'] is not None
                        and row['last_maintenance_count'] <= row['switch_count']):
                    row['switches_since_maintenance'] = row['switch_count'] - row['last_maintenance_count']
                else:
                    row['switches_since_maintenance'] = None
                heads.append(row)
            return heads
        except (KeyError, TypeError, AttributeError) as exc:
            raise MoonrakerError('U1 head maintenance counters are unavailable') from exc

    def motion_evidence(self):
        """Read experimental Klipper capture. Never applies it to inventory."""
        result = self._json('/printer/objects/query?print_stats&tracker_motion')
        try:
            objects = result['status']
            capture = objects['tracker_motion']['capture']
            stats = objects['print_stats']
            if (not isinstance(capture, dict) or capture.get('schema') != 1
                    or capture.get('state') not in ('active', 'completed', 'not_completed')
                    or not isinstance(capture.get('valid'), bool)
                    or not isinstance(capture.get('filename'), str)
                    or capture['filename'] != stats.get('filename')
                    or not isinstance(capture.get('capture_id'), str) or not capture['capture_id']
                    or not isinstance(capture.get('epoch'), str) or not capture['epoch']):
                raise ValueError('Motion capture identity is unavailable')
            lengths = capture.get('head_mm')
            if (not isinstance(lengths, list) or len(lengths) != 4
                    or any(isinstance(x, bool) or not isinstance(x, (int, float))
                           or not math.isfinite(x) or x < 0 for x in lengths)):
                raise ValueError('Motion capture is invalid')
            return dict(capture)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise MoonrakerError(f'U1 motion evidence unavailable: {exc}') from exc

    def tag_snapshot(self):
        """Read currently scanned physical tag IDs without changing the U1."""
        result = self._json('/printer/objects/query?filament_detect')
        try:
            return read_tag_uids(result['status']['filament_detect'])
        except (KeyError, TypeError, ValueError) as exc:
            raise MoonrakerError(f'U1 tag status unavailable: {exc}') from exc

    def mapping_snapshot(self, filename):
        result = self._json("/printer/objects/query?print_stats&print_task_config")
        try:
            objects = result["status"]
            stats, config = objects["print_stats"], objects["print_task_config"]
            if stats["state"] not in ("printing", "paused") or stats.get("filename") != filename:
                raise MoonrakerError("Active print changed while reading U1 tool mapping")
            mapping = validate_mapping(config.get("extruder_map_table"))
            auto = config.get("auto_replenish_filament")
            result = {"mapping": mapping, "auto_replenish": auto if type(auto) is bool else None}
            if "extruders_replenished" in config:
                result["replenished"] = validate_mapping(config["extruders_replenished"])
            return result
        except (KeyError, TypeError, AttributeError, MappingError) as exc:
            raise MoonrakerError(f"U1 tool mapping could not be verified: {exc}") from exc

    def history(self):
        jobs = []
        for start in range(0, 500, 50):
            result = self._json(f"/server/history/list?limit=50&start={start}&order=desc")
            if not isinstance(result.get("jobs"), list):
                raise MoonrakerError("Moonraker history is unavailable")
            page = result["jobs"]
            jobs.extend(page)
            if len(page) < 50 or start + 50 >= result.get("count", 0):
                break
        return sorted(jobs, key=lambda job: job.get("start_time") or 0)

    def fingerprint(self, filename):
        # Metadata is small. The file itself is streamed; no large G-code buffer.
        metadata = self._json("/server/files/metadata?" + urlencode({"filename": filename}))
        if not isinstance(metadata, dict):
            raise MoonrakerError("Remote G-code metadata is invalid")
        expected_size = metadata.get("size")
        digest = hashlib.sha256()
        size = 0
        path = "/server/files/gcodes/" + quote(filename, safe="/")
        with self._open(path) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if isinstance(expected_size, int) and expected_size != size:
            raise MoonrakerError("Remote G-code size changed during verification")
        return digest.hexdigest(), size

    def inspect_gcode(self, filename):
        """Read the exact remote file once for its identity and T0–T3 usage."""
        self.last_inspection_metadata = None
        metadata = self._json("/server/files/metadata?" + urlencode({"filename": filename}))
        if not isinstance(metadata, dict):
            raise MoonrakerError("Remote G-code metadata is invalid")
        expected_size = metadata.get("size")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise MoonrakerError("Remote G-code size is unavailable")
        if expected_size > MAX_INSPECT_BYTES:
            raise MoonrakerError("Remote G-code exceeds the inspection size limit")
        digest = hashlib.sha256()
        size = 0
        path = "/server/files/gcodes/" + quote(filename, safe="/")
        with tempfile.TemporaryFile() as temporary:
            with self._open(path) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_INSPECT_BYTES:
                        raise MoonrakerError("Remote G-code exceeds the inspection size limit")
                    digest.update(chunk)
                    temporary.write(chunk)
            if expected_size != size:
                raise MoonrakerError("Remote G-code size changed during verification")
            latest = self._json("/server/files/metadata?" + urlencode({"filename": filename}))
            if not isinstance(latest, dict):
                raise MoonrakerError("Remote G-code metadata is invalid")
            if (latest.get("size") != expected_size
                    or latest.get("modified") != metadata.get("modified")):
                raise MoonrakerError("Remote G-code changed during verification")
            material_fields = ("slicer", "filament_type", "filament_weight")
            modified = metadata.get("modified")
            if (not isinstance(modified, bool) and isinstance(modified, (int, float)) and math.isfinite(modified)
                    and all(latest.get(k) == metadata.get(k) for k in material_fields)):
                self.last_inspection_metadata = {k: latest.get(k) for k in material_fields}
            temporary.seek(0)
            weights = parse_u1_gcode_handle(temporary)
            if self.last_inspection_metadata is not None:
                self.last_inspection_metadata['filament_parameters'] = parse_filament_parameters_handle(temporary)
        return digest.hexdigest(), size, weights


def _set_status(store, connected, state, filename="", error="", active_head=None, active_job_key=None):
    store.update(lambda db: db.__setitem__("monitor", {
        "connected": connected, "state": state, "filename": filename,
        "error": error[:500], "checked_at": time.time(), "active_head": active_head, "active_job_key": active_job_key
    }))


class GuardRuntime:
    """Arm strict protection only after observing the printer not printing."""

    def __init__(self):
        self.mode = None
        self.target = None
        self.armed = False


def _active_job(current, jobs):
    if current["state"] not in ("printing", "paused") or not current["filename"]:
        return None
    active = jobs[-1] if jobs else None
    if (not isinstance(active, dict) or active.get("status") != "in_progress"
            or not isinstance(active.get("job_id"), str) or not active["job_id"]
            or isinstance(active.get("start_time"), bool)
            or not isinstance(active.get("start_time"), (int, float))
            or not math.isfinite(active["start_time"]) or active["start_time"] <= 0
            or not isinstance(active.get("filename"), str)
            or active["filename"] != current["filename"]):
        return None  # History may appear shortly after print_stats changes.
    return active


def _same_active_job(config, active, client):
    """Recheck job identity immediately before sending a pause command."""
    current = client.status()
    if (current["klippy_state"] != "ready" or current["state"] != "printing"
            or current["filename"] != active["filename"]):
        return False
    latest = _active_job(current, client.history())
    return latest is not None and run_key(config, latest) == run_key(config, active)


def _still_same_job(config, active, client):
    current = client.status()
    latest = _active_job(current, client.history())
    return latest is not None and run_key(config, latest) == run_key(config, active)


def _finish_pause_request(store, config, active, client, key, reason, mapping_evidence=None):
    """Wait for one pause request without blocking monitoring or issuing retries."""
    state = "pause_failed"
    detail = "Print or guard settings changed before pause; no command sent"
    disable_strict = False
    try:
        latest = store.read()
        live_config = latest["printer"]
        guard = latest.get("last_guard") or {}
        if (not live_config["enabled"] or live_config.get("guard_mode") != "strict"
                or live_config["host"] != config["host"] or live_config["port"] != config["port"]
                or guard.get("job_key") != key or guard.get("state") != "pause_requested"
                or not _same_active_job(config, active, client)):
            raise MoonrakerError(detail)
        if mapping_evidence is not None and client.mapping_snapshot(active["filename"]) != mapping_evidence:
            raise MoonrakerError("U1 tool mapping changed before pause; no command sent")
        try:
            LOGGER.info("Guard requesting pause for %s", active["filename"])
            client.pause()
            after = client.status()
            paused_job = _active_job(after, client.history())
            if (after["state"] != "paused" or paused_job is None
                    or run_key(config, paused_job) != key):
                raise MoonrakerError("Pause response received, but this job is not confirmed paused")
            state, detail = "paused", reason
        except Exception as exc:
            # A timed-out or disconnected request can still execute later on U1.
            # Never resend it or offer resume/cancel on an unconfirmed state.
            state, detail, disable_strict = "pause_uncertain", str(exc)[:500], True
    except Exception as exc:
        detail = str(exc)[:500]

    def finish(db):
        guard = db.get("last_guard") or {}
        if guard.get("job_key") == key and guard.get("state") == "pause_requested":
            guard["state"], guard["reason"] = state, detail
            printer = db["printer"]
            if (disable_strict and printer["host"] == config["host"]
                    and printer["port"] == config["port"] and printer.get("guard_mode") == "strict"):
                printer["guard_mode"] = "warn"

    store.update(finish)
    LOGGER.info("Guard pause outcome for %s: %s%s", active["filename"], state,
                f" ({detail})" if detail else "")


def _inspect_started_job(store, snapshot, config, current, jobs, client, runtime=None):
    active = _active_job(current, jobs)
    if active is None:
        return None
    key = run_key(config, active)
    previous = snapshot.get("last_guard") or {}
    if previous.get("state") in ("pause_requested", "pause_uncertain", "resume_requested", "cancel_requested", "action_uncertain") and previous.get("job_key") != key:
        if runtime is not None:
            runtime.armed = False
        LOGGER.warning("Guard command outcome unresolved; not issuing a command for another job")
        return None
    if previous.get("job_key") == key:
        return None
    fingerprint = None
    mapping = None
    logical_weights = None
    mapping_evidence = None
    try:
        before = client.mapping_snapshot(active["filename"])
        sha, size, logical_weights = client.inspect_gcode(active["filename"])
        after = client.mapping_snapshot(active["filename"])
        if before != after or not _still_same_job(config, active, client):
            raise MoonrakerError("U1 mapping or active job changed during verification")
        mapping = after["mapping"]
        weights = physical_weights(logical_weights, mapping)
        mapping_evidence = after
        fingerprint = (sha, size)
        reason = ("G-code → U1: " + ", ".join(f"T{i} → T{mapping[i]}" for i in range(4) if logical_weights[i] > 0)
                  if any(logical_weights[i] > 0 and mapping[i] != i for i in range(4)) else "")
    except (GCodeError, MappingError, MoonrakerError, OSError) as exc:
        weights = None
        reason = str(exc)[:300]

    mode = config.get("guard_mode", "warn")

    def save(db):
        material_checks = None
        material_warning = False
        if weights is None:
            rows = []
            summary = "Print start: unverified"
            risky = True
        else:
            rows = check(weights, db)  # Use assignments at the time of inspection.
            risky = has_problem(rows)
            summary = "Print start: attention required" if risky else "Print start: OK"
            metadata = getattr(client, "last_inspection_metadata", None)
            if metadata is not None:
                material_checks = compare_materials(metadata, logical_weights, mapping, db)
                mismatches = [f'T{row["head"]}' for row in material_checks if row['status'] == 'mismatch']
                if mismatches:
                    material_warning = True
                    if not risky:
                        summary = "Print start: material advisory"
                    note = ("Несовпадение материала: " if db.get('language') == 'ru' else "Material mismatch: ") + ', '.join(mismatches)
                    note += (". Проверьте материал; это предупреждение не останавливает принтер." if db.get('language') == 'ru'
                             else ". Verify material; this advisory does not pause the printer.")
                    for item in material_checks:
                        if item['status'] != 'mismatch' or not item['candidates']:
                            continue
                        names = [db['spools'][spool_id]['name'] for spool_id in item['candidates'] if spool_id in db['spools']]
                        if names:
                            note += ((" Кандидаты по типу и остатку (проверьте назначение): " if db.get('language') == 'ru'
                                      else " Candidates by type and balance (verify assignment): ") + ', '.join(names[:5]) + '.')
                    reason_text = (reason + ' · ' if reason else '') + note
                else:
                    reason_text = reason
            else:
                material_checks = compare_materials(None, logical_weights, mapping, db)
                reason_text = reason
            if any(row['status'] == 'unknown' for row in material_checks):
                note = ("Тип материала для некоторых головок не подтверждён." if db.get('language') == 'ru'
                        else "Material type is unverified for some used heads.")
                reason_text = (reason_text + ' · ' if reason_text else '') + note
        if weights is None:
            reason_text = reason
        db["last_preflight"] = {
            "source": "print_start", "job_key": key, "filename": active["filename"],
            "summary": summary, "rows": rows, "reason": reason_text,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if mapping is not None:
            db["last_preflight"]["tool_mapping"] = mapping
            db["last_preflight"]["logical_weights"] = logical_weights
        if material_checks is not None:
            db["last_preflight"]["material_checks"] = material_checks
        should_pause = (risky and mode == "strict" and runtime is not None
                        and runtime.armed and current["state"] == "printing")
        state = "pause_requested" if should_pause else ("warning" if risky or material_warning else "ok")
        db["last_guard"] = {
            "job_key": key, "filename": active["filename"], "state": state,
            "summary": summary, "reason": reason_text, "checked_at": time.time(),
        }
        return summary, state

    summary, state = store.update(save)
    if runtime is not None:
        runtime.armed = False
    if state == "pause_requested":
        threading.Thread(target=_finish_pause_request, args=(store, config, active, client, key, reason, mapping_evidence),
                         daemon=True, name="guard-pause-request").start()
    LOGGER.info("%s: %s", active["filename"], summary)
    return active["filename"], fingerprint, mapping_evidence, logical_weights


def decide_guard(store, action, client_factory=MoonrakerClient):
    """Act only on the exact job that this Tracker instance previously paused."""
    if action not in ("resume", "cancel"):
        raise MoonrakerError("Unknown guard action")
    snapshot = store.read()
    config = snapshot["printer"]
    guard = snapshot.get("last_guard") or {}
    if not config["enabled"] or guard.get("state") != "paused":
        raise MoonrakerError("No Tracker-paused print is awaiting a decision")
    client = client_factory(config["host"], config["port"])
    current = client.status()
    if current["state"] != "paused" or current["filename"] != guard["filename"]:
        raise MoonrakerError("The printer is no longer paused on that file")
    active = _active_job(current, client.history())
    if active is None or run_key(config, active) != guard["job_key"]:
        raise MoonrakerError("The paused printer job no longer matches the guard")

    def mark_pending(db):
        current_guard = db.get("last_guard") or {}
        printer = db["printer"]
        if (current_guard.get("job_key") != guard["job_key"] or current_guard.get("state") != "paused"
                or not printer["enabled"] or printer["host"] != config["host"] or printer["port"] != config["port"]):
            raise MoonrakerError("Guard or printer settings changed before the action")
        current_guard["state"] = action + "_requested"

    store.update(mark_pending)
    try:
        getattr(client, action)()
        after = client.status()
        expected = "printing" if action == "resume" else "cancelled"
        if after["state"] != expected or after["filename"] != guard["filename"]:
            raise MoonrakerError(f"Could not verify printer {action} result")
    except Exception as exc:
        def mark_uncertain(db):
            current_guard = db.get("last_guard") or {}
            if current_guard.get("job_key") == guard["job_key"] and current_guard.get("state") == action + "_requested":
                current_guard["state"] = "action_uncertain"
                current_guard["reason"] = str(exc)[:500]
                printer = db["printer"]
                if printer["host"] == config["host"] and printer["port"] == config["port"] and printer.get("guard_mode") == "strict":
                    printer["guard_mode"] = "warn"
        store.update(mark_uncertain)
        LOGGER.warning("Guard %s outcome for %s is uncertain: %s", action, guard["filename"], exc)
        raise MoonrakerError(f"The {action} outcome is unknown. Check the U1 directly; do not repeat the command.") from exc

    def save(db):
        if ((db.get("last_guard") or {}).get("job_key") == guard["job_key"]
                and db["last_guard"].get("state") == action + "_requested"):
            db["last_guard"]["state"] = "resumed" if action == "resume" else "cancelled"

    store.update(save)
    return action


def poll_once(store, client_factory=MoonrakerClient, guard_runtime=None, experimental_motion=False):
    snapshot = store.read()
    config = snapshot["printer"]
    if not config["enabled"]:
        if guard_runtime is not None:
            guard_runtime.armed = False
        if snapshot["monitor"]["state"] != "disabled":
            invalidate_active_runs(store, config)
            _set_status(store, False, "disabled")
        return
    client = client_factory(config["host"], config["port"])
    mode = config.get("guard_mode", "warn")
    target = (config["host"].casefold(), config["port"])
    if guard_runtime is not None and (guard_runtime.mode != mode or guard_runtime.target != target):
        if guard_runtime.target is not None and guard_runtime.target != target:
            invalidate_active_runs(store, {"host": guard_runtime.target[0], "port": guard_runtime.target[1]})
        guard_runtime.mode = mode
        guard_runtime.target = target
        guard_runtime.armed = False
    try:
        current = client.status()
        jobs = client.history()
    except Exception as exc:
        if guard_runtime is not None:
            guard_runtime.armed = False
        LOGGER.warning("Moonraker unavailable: %s", exc)
        invalidate_active_runs(store, config)
        _set_status(store, False, "disconnected", error=str(exc))
        return
    selected_head = None
    if current["state"] == "printing" and current["klippy_state"] == "ready":
        try:
            selected_head = client.active_head(current["filename"])
        except Exception as exc:
            LOGGER.debug("Selected head unavailable: %s", exc)
    status_job = _active_job(current, jobs)
    _set_status(store, True, current["state"], current["filename"],
                "" if current["klippy_state"] == "ready" else f'Klippy: {current["klippy_state"]}',
                active_head=selected_head,
                active_job_key=run_key(config, status_job) if status_job else None)
    if guard_runtime is not None and current["state"] in ("standby", "complete", "cancelled", "error"):
        guard_runtime.armed = True
    fingerprints = {}
    observed_weights = {}
    inspected = (_inspect_started_job(store, snapshot, config, current, jobs, client, guard_runtime)
                 if mode != "off" else None)
    if inspected and inspected[1]:
        fingerprints[inspected[0]] = inspected[1]
        observed_weights[inspected[0]] = inspected[3]
    active = _active_job(current, jobs)
    motion_capture = None
    if experimental_motion and current['state'] in ('printing', 'paused', 'complete'):
        try:
            motion_capture = client.motion_evidence()
        except Exception as exc:
            LOGGER.debug('Experimental motion capture unavailable: %s', exc)
    known_runs = set(snapshot["runs"])
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("filename"), str):
            continue
        if not isinstance(job.get("job_id"), str) or not isinstance(job.get("start_time"), (int, float)):
            continue
        key = run_key(config, job)
        active_match = (job.get("status") == "in_progress" and active is not None
                        and run_key(config, active) == key)
        mapping_before = None
        used_guard_inspection = active_match and inspected is not None and inspected[0] == job["filename"]
        if active_match and not used_guard_inspection:
            try:
                mapping_before = client.mapping_snapshot(job["filename"])
            except Exception as exc:
                LOGGER.warning("Cannot read U1 mapping for accounting: %s", exc)
        remote = None
        if key not in known_runs:
            name = file_name(job["filename"]).casefold()
            has_plan = any(plan["filename"].casefold() == name
                       and plan["printer"]["host"].casefold() == config["host"].casefold()
                       and plan["printer"]["port"] == config["port"]
                       for plan in snapshot["plans"].values())
            if not has_plan and not active_match:
                continue
            if job["filename"] not in fingerprints:
                try:
                    if active_match and hasattr(client, "inspect_gcode"):
                        sha, size, weights = client.inspect_gcode(job["filename"])
                        fingerprints[job["filename"]] = (sha, size)
                        observed_weights[job["filename"]] = weights
                    else:
                        fingerprints[job["filename"]] = client.fingerprint(job["filename"])
                except Exception as exc:
                    LOGGER.warning("Cannot verify remote G-code %s: %s", job["filename"], exc)
                    continue
            remote = fingerprints[job["filename"]]
        mapping_evidence = None
        if active_match:
            try:
                if used_guard_inspection:
                    mapping_evidence = inspected[2]  # None means the guard could not verify it.
                elif mapping_before is not None:
                    mapping_after = client.mapping_snapshot(job["filename"])
                    if mapping_before != mapping_after or not _still_same_job(config, active, client):
                        raise MoonrakerError("Active print or tool mapping changed during verification")
                    mapping_evidence = mapping_after
            except Exception as exc:
                LOGGER.warning("Cannot verify U1 mapping for accounting: %s", exc)
        metadata = getattr(client, 'last_inspection_metadata', None)
        weights = observed_weights.get(job['filename'])
        if active_match and mapping_evidence and isinstance(metadata, dict) and isinstance(weights, list):
            params = metadata.get('filament_parameters')
            types = metadata.get('filament_type')
            if isinstance(params, list) and len(params) == 4:
                # Process-local hint for diagnostics only. It is never a spool
                # identity assertion or an authorization to debit inventory.
                store._motion_slicer_profile = {
                    'filename': job['filename'], 'started_at': job['start_time'],
                    'mapping': mapping_evidence['mapping'], 'logical_weights': list(weights),
                    'replenished': mapping_evidence.get('replenished'),
                    'parameters': params, 'filament_type': types,
                }
        result = apply_history_job(store, config, job, remote, mapping_evidence,
                                   observed_weights.get(job["filename"]) if active_match else None)
        if result == 'review' and motion_capture and job['filename'] == motion_capture.get('filename'):
            try:
                if active_match and motion_capture.get('state') == 'active':
                    begin_motion_watch(store, key, motion_capture)
                elif job.get('status') == 'completed' and motion_capture.get('state') == 'completed':
                    commit_motion_watch(store, key, motion_capture)
            except (ValueError, TypeError) as exc:
                LOGGER.info('Motion capture requires review for job %s: %s', job['job_id'], exc)
        if result:
            known_runs.add(key)
            LOGGER.info("Printer job %s: %s", job["job_id"], result)


class PrinterMonitor:
    def __init__(self, store, interval=10, strict_interval=2, on_guard=None, experimental_motion=False):
        self.store = store
        self.interval = interval
        self.strict_interval = strict_interval
        self.on_guard = on_guard
        self.experimental_motion = experimental_motion
        self.stop_event = threading.Event()
        self.thread = None
        self.guard_runtime = GuardRuntime()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="printer-monitor")
        self.thread.start()

    def _run(self):
        invalidate_active_runs(self.store, self.store.read()["printer"])
        def recover(db):
            guard = db.get("last_guard") or {}
            state = guard.get("state")
            if state in ("pause_requested", "resume_requested", "cancel_requested"):
                guard["state"] = "pause_uncertain" if state == "pause_requested" else "action_uncertain"
                guard["reason"] = "Tracker restarted while a printer command was pending; check the U1 directly."
                if db["printer"].get("guard_mode") == "strict":
                    db["printer"]["guard_mode"] = "warn"
                return True
            return False

        recovered = self.store.update(recover)
        initial = self.store.read()
        guard = initial.get("last_guard") or {}
        previous = (guard.get("job_key"), guard.get("state"))
        if recovered and self.on_guard:
            threading.Thread(target=self.on_guard, args=(initial,), daemon=True,
                             name="guard-notification").start()
        while not self.stop_event.is_set():
            wait = self.interval
            try:
                poll_once(self.store, guard_runtime=self.guard_runtime, experimental_motion=self.experimental_motion)
                latest = self.store.read()
                config = latest["printer"]
                if config["enabled"] and config.get("guard_mode") == "strict":
                    wait = self.strict_interval
                guard = latest.get("last_guard") or {}
                current_guard = (guard.get("job_key"), guard.get("state"))
                if current_guard != previous:
                    previous = current_guard
                    if self.on_guard and guard.get("state") in ("warning", "pause_requested", "paused", "pause_failed", "pause_uncertain", "action_uncertain"):
                        threading.Thread(target=self.on_guard, args=(latest,), daemon=True,
                                         name="guard-notification").start()
            except Exception:
                LOGGER.exception("Printer monitor error")
            self.stop_event.wait(wait)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)
