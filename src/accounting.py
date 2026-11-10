from spoolman_bridge import book
"""Planned G-code snapshots and idempotent physical-print accounting."""
import hashlib
import math
import time
import uuid
import copy

from tool_mapping import MappingError, physical_weights, validate_mapping
from motion_reconcile import estimate_capture

def fingerprint_file(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def file_name(value):
    return str(value).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".pp")


def create_plan(store, path, output_name, weights, db_snapshot, now=None):
    sha, size = fingerprint_file(path)
    filename = file_name(output_name or path)
    if not filename:
        raise ValueError("G-code output filename is unavailable")
    plan_id = uuid.uuid4().hex
    plan = {"filename": filename, "sha256": sha, "size": size,
            "weights": list(weights),
            "spool_ids": [db_snapshot["slots"][str(i)] for i in range(1, 5)],
            "created_at": time.time() if now is None else now,
            "status": "planned", "printer": dict(db_snapshot["printer"])}
    store.update(lambda db: db["plans"].__setitem__(plan_id, plan))
    return plan_id


def run_key(printer, job):
    raw = f'{printer["host"].casefold()}:{printer["port"]}|{job["job_id"]}|{job["start_time"]}'
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _set_plan_status(plan, status):
    # A later ambiguous run must not erase a previously committed result.
    if plan["status"] != "committed" or status == "committed":
        plan["status"] = status


def invalidate_active_runs(store, printer):
    """A monitoring gap makes physical-spool accounting unprovable."""
    def change(db):
        for run in db["runs"].values():
            plan = db["plans"][run["plan_id"]]
            saved = plan["printer"]
            if (run["status"] == "active" and saved["host"].casefold() == printer["host"].casefold()
                    and saved["port"] == printer["port"]):
                run["status"] = "review"
                _set_plan_status(plan, "review")
                run["review_reason"] = "Monitoring was interrupted before completion"
    store.update(change)


def _matching_plans(db, printer, job, remote_fingerprint):
    if not remote_fingerprint:
        return []
    sha, size = remote_fingerprint
    name = file_name(job["filename"]).casefold()
    candidates = [(key, plan) for key, plan in db["plans"].items()
                  if plan["filename"].casefold() == name and plan["sha256"] == sha
                  and plan["size"] == size
                  and plan["printer"]["host"].casefold() == printer["host"].casefold()
                  and plan["printer"]["port"] == printer["port"]
                  and plan["created_at"] <= job["start_time"]]
    return sorted(candidates, key=lambda pair: pair[1]["created_at"], reverse=True)


def apply_history_job(store, printer, job, remote_fingerprint=None, mapping_evidence=None, observed_weights=None):
    """One locked transaction per history event; returns its new/current status."""
    status = job.get("status")
    if status not in ("in_progress", "completed", "cancelled", "error", "klippy_shutdown", "klippy_disconnect", "interrupted"):
        return None
    if not isinstance(job.get("job_id"), str) or not job["job_id"] or not isinstance(job.get("filename"), str) or not job["filename"]:
        return None
    if (isinstance(job.get("start_time"), bool)
            or not isinstance(job.get("start_time"), (int, float))
            or not math.isfinite(job["start_time"]) or job["start_time"] <= 0):
        return None
    key = run_key(printer, job)

    def change(db):
        selected = db["printer"]
        if (not selected.get("enabled") or selected["host"].casefold() != printer["host"].casefold()
                or selected["port"] != printer["port"]):
            return None
        run = db["runs"].get(key)
        if run and run["status"] != "active":
            # A printer history record can transiently report an error before
            # the very same job resumes. Do not apply this to cancellations.
            if run['status'] == 'error' and status == 'cancelled':
                run['status'] = 'cancelled'
                run['terminal_status'] = 'cancelled'
                _set_plan_status(db['plans'][run['plan_id']], 'cancelled')
            if run['status'] == 'error' and status in ('in_progress', 'completed'):
                run['status'] = 'review'
                run['review_reason'] = 'Print resumed after an error; continuity requires verification'
                _set_plan_status(db['plans'][run['plan_id']], 'review')
            if run['status'] == 'review' and status == 'in_progress' and run.get('terminal_status') in ('error', 'interrupted'):
                run.pop('terminal_status', None)
            if run["status"] == "review" and status == "in_progress" and isinstance(mapping_evidence, dict):
                try:
                    validate_mapping(mapping_evidence.get("mapping"))
                    replenished = mapping_evidence.get("replenished")
                    if replenished is not None and validate_mapping(replenished) != [0, 1, 2, 3]:
                        run["replenishment_observed"] = True
                except MappingError:
                    pass
            if (run['status'] == 'review' and status in ('completed', 'cancelled')
                    and run.get('terminal_status') in ('error', 'interrupted')):
                run['terminal_status'] = status
            if run["status"] == "review" and status != "in_progress" and not run.get("terminal_status"):
                run["terminal_status"] = status
            return run["status"]
        if run is None:
            candidates = _matching_plans(db, printer, job, remote_fingerprint)
            if not candidates and status == "in_progress" and remote_fingerprint and observed_weights is not None:
                try:
                    # Reject malformed metadata before creating a persistent job record.
                    physical_weights(observed_weights, [0, 1, 2, 3])
                except (MappingError, TypeError, ValueError):
                    return None
                sha, size = remote_fingerprint
                plan_id = uuid.uuid4().hex
                plan = {"filename": file_name(job["filename"]), "sha256": sha, "size": size,
                        "weights": list(observed_weights),
                        "spool_ids": [db["slots"][str(i)] for i in range(1, 5)],
                        "created_at": float(job["start_time"]), "status": "planned",
                        "printer": dict(printer)}
                db["plans"][plan_id] = plan
                candidates = [(plan_id, plan)]
            if not candidates:
                return None
            plan_id, plan = candidates[0]
            mappings = {(tuple(p["spool_ids"]), tuple(p["weights"])) for _, p in candidates}
            run = {"job_id": job["job_id"], "plan_id": plan_id,
                   "start_time": float(job["start_time"]), "status": "active",
                   "filename": job["filename"]}
            if db.get('spoolman', {}).get('mode') in ('read', 'send'):
                run['spoolman_epoch'] = db['spoolman']['epoch']
            db["runs"][key] = run
            if len(mappings) > 1:
                run["status"] = "review"
                _set_plan_status(plan, "review")
                run["review_reason"] = "Conflicting export plans"
                return "review"
            if status not in ("in_progress", "completed"):
                run["status"] = "cancelled" if status == "cancelled" else "error"
                _set_plan_status(plan, run["status"])
                return run["status"]
            try:
                if status != "in_progress" or not isinstance(mapping_evidence, dict):
                    raise MappingError("No verified mapping from the active print")
                mapping = validate_mapping(mapping_evidence.get("mapping"))
                required = physical_weights(plan["weights"], mapping)
                current_spools = [db["slots"][str(i)] for i in range(1, 5)]
                if any(required[i] and (not current_spools[i] or current_spools[i] != plan["spool_ids"][i])
                       for i in range(4)):
                    raise MappingError("Spool assignment changed since export")
                run.update({"tool_mapping": mapping, "physical_weights": required,
                            "physical_spool_ids": current_spools})
                replenished = mapping_evidence.get("replenished")
                if replenished is not None and validate_mapping(replenished) != [0, 1, 2, 3]:
                    run["replenishment_observed"] = True
                if mapping_evidence.get("auto_replenish") is not False:
                    raise MappingError("Automatic replenishment cannot be ruled out; initial spool and estimate saved for review")
            except MappingError as exc:
                run["status"] = "review"
                if status == "completed":
                    run["terminal_status"] = status
                _set_plan_status(plan, "review")
                run["review_reason"] = str(exc)
                return "review"
            _set_plan_status(plan, "active")
        plan = db["plans"][run["plan_id"]]
        if status == "in_progress":
            try:
                mapping = validate_mapping(mapping_evidence.get("mapping") if isinstance(mapping_evidence, dict) else None)
                if (mapping_evidence.get("auto_replenish") is not False
                        or mapping != run.get("tool_mapping")
                        or not isinstance(run.get("physical_weights"), list)
                        or not isinstance(run.get("physical_spool_ids"), list)
                        or any(run["physical_weights"][i] and db["slots"][str(i + 1)] != run["physical_spool_ids"][i]
                               for i in range(4))):
                    raise MappingError("Mapping or spool assignment is no longer verified")
            except MappingError as exc:
                run["status"] = "review"
                _set_plan_status(plan, "review")
                run["review_reason"] = str(exc)
                return "review"
            return "active"
        if status == "completed":
            if (not isinstance(run.get("physical_weights"), list)
                    or not isinstance(run.get("physical_spool_ids"), list)
                    or any(run["physical_weights"][i] and db["slots"][str(i + 1)] != run["physical_spool_ids"][i]
                           for i in range(4))):
                run["status"] = "review"
                _set_plan_status(plan, "review")
                run["review_reason"] = "Physical spool snapshot unavailable or assignment changed"
                return "review"
            consumption = {}
            for spool_id, grams in zip(run["physical_spool_ids"], run["physical_weights"]):
                if grams > 0:
                    if not spool_id or spool_id not in db["spools"]:
                        run["status"] = "review"
                        _set_plan_status(plan, "review")
                        run["review_reason"] = "The captured spool is no longer available"
                        return "review"
                    consumption[spool_id] = consumption.get(spool_id, 0.0) + grams
            book(db, key, consumption)
            run["status"] = "committed"
            _set_plan_status(plan, "committed")
            return "committed"
        run["status"] = "cancelled" if status == "cancelled" else "error"
        if status == 'cancelled':
            run['terminal_status'] = 'cancelled'
        _set_plan_status(plan, run["status"])
        return run["status"]

    return store.update(change)


def reconcile_completed_review(store, key, consumption, measurements=None):
    """Apply explicit per-spool amounts to a completed review, at most once.

    Amounts must come from the user or independently verified measurements;
    the printer's aggregate filament count cannot identify a replacement spool.
    """
    if not isinstance(consumption, dict) or not consumption:
        raise ValueError("Per-spool consumption is required")
    amounts = {}
    for spool_id, value in consumption.items():
        if not isinstance(spool_id, str) or not spool_id or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid spool or consumption")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Consumption must be finite and non-negative")
        amounts[spool_id] = float(value)
    if measurements is None:
        measurements = {}
    if not isinstance(measurements, dict) or not set(measurements).issubset(amounts):
        raise ValueError('Invalid spool weighing evidence')
    checked_measurements = {}
    for spool_id, pair in measurements.items():
        if not isinstance(pair, dict) or set(pair) != {'before_g', 'after_g'}:
            raise ValueError('Both scale readings are required')
        before, after = pair['before_g'], pair['after_g']
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (before, after))
                or before < after or abs((before - after) - amounts[spool_id]) > 0.001):
            raise ValueError('Scale readings do not match the recorded usage')
        checked_measurements[spool_id] = {'before_g': float(before), 'after_g': float(after)}

    def change(db):
        run = db["runs"].get(key)
        if not run:
            raise ValueError("Unknown print")
        if run["status"] == "committed" and run.get("accounting_method") == "manual_review":
            if run.get("manual_consumption") == amounts and run.get('manual_measurements', {}) == checked_measurements:
                return False
            raise ValueError("This print was already reconciled with different amounts")
        if run["status"] != "review" or run.get("terminal_status") != "completed":
            raise ValueError("A completed print awaiting review is required")
        for spool_id, grams in amounts.items():
            spool = db["spools"].get(spool_id)
            if spool is None or grams > spool["remaining_g"]:
                raise ValueError("Spool is unavailable or consumption exceeds its balance")
        book(db, key, amounts)
        run["status"] = "committed"
        run["accounting_method"] = "manual_review"
        run["manual_consumption"] = amounts
        if checked_measurements:
            run['manual_measurements'] = checked_measurements
        _set_plan_status(db["plans"][run["plan_id"]], "committed")
        return True

    return store.update(change)


def begin_motion_watch(store, key, capture):
    """Snapshot a verified active capture and spool configuration; no debit."""
    if not isinstance(capture, dict) or capture.get('state') != 'active' or capture.get('valid') is not True or capture.get('identity_verified') is not True:
        return False
    def change(db):
        run = db['runs'].get(key)
        if not run or run['status'] != 'review' or run.get('terminal_status'):
            return False
        if run.get('motion_watch'):
            return False
        start = {name: copy.deepcopy(capture.get(name)) for name in
                 ('state', 'valid', 'identity_verified', 'epoch', 'capture_id', 'filename', 'started_at', 'initial_tag_uids')}
        if (start['filename'] != run['filename'] or not isinstance(start['epoch'], str) or not start['epoch']
                or not isinstance(start['capture_id'], str) or not start['capture_id']
                or len(start['epoch']) > 128 or len(start['capture_id']) > 128
                or isinstance(start['started_at'], bool) or not isinstance(start['started_at'], (int, float))
                or not math.isfinite(start['started_at']) or abs(start['started_at'] - run['start_time']) > 10
                or not isinstance(start['initial_tag_uids'], list) or len(start['initial_tag_uids']) != 4
                or any(x is not None and (not isinstance(x, str) or len(x) > 20) for x in start['initial_tag_uids'])):
            return False
        slots = [db['slots'][str(i)] for i in range(1, 5)]
        calibrations = {spool_id: copy.deepcopy(db['spools'][spool_id]['calibration'])
                        for spool_id in slots if spool_id and 'calibration' in db['spools'][spool_id]}
        run['motion_watch'] = {'start': start, 'slots': slots, 'calibrations': calibrations}
        return True
    return store.update(change)


def commit_motion_watch(store, key, capture):
    """Atomically book a completed, fully evidenced prototype capture once."""
    def change(db):
        run = db['runs'].get(key)
        if not run:
            raise ValueError('Unknown job')
        if run['status'] == 'committed' and run.get('accounting_method') == 'motion_estimate':
            if (run.get('motion_capture_id') == capture.get('capture_id')
                    and run.get('motion_epoch') == capture.get('epoch')):
                return False
            raise ValueError('A different capture was already booked')
        if run['status'] != 'review' or run.get('terminal_status') != 'completed' or not run.get('motion_watch'):
            raise ValueError('An observed completed job awaiting review is required')
        watch = run['motion_watch']
        for other_key, other in db['runs'].items():
            if (other_key != key and other.get('motion_capture_id') == capture.get('capture_id')
                    and other.get('motion_epoch') == capture.get('epoch')):
                raise ValueError('Capture already belongs to another job')
        slots = [db['slots'][str(i)] for i in range(1, 5)]
        current_cal = {spool_id: copy.deepcopy(db['spools'][spool_id]['calibration'])
                       for spool_id in slots if spool_id and 'calibration' in db['spools'][spool_id]}
        job = {'filename': run['filename'], 'status': run['terminal_status'], 'start_time': run['start_time']}
        amounts = estimate_capture(watch['start'], capture, job, watch['slots'], slots, watch['calibrations'], current_cal)
        for spool_id, grams in amounts.items():
            if spool_id not in db['spools'] or grams > db['spools'][spool_id]['remaining_g']:
                raise ValueError('Spool unavailable or its balance is below the estimated usage')
        book(db, key, amounts)
        run.update({'status': 'committed', 'accounting_method': 'motion_estimate',
                    'motion_consumption': amounts, 'motion_capture_id': capture['capture_id'], 'motion_epoch': capture['epoch']})
        _set_plan_status(db['plans'][run['plan_id']], 'committed')
        return True
    if not isinstance(capture, dict):
        raise ValueError('Capture unavailable')
    return store.update(change)


def commit_unchanged_slicer_estimate(store, key, evidence):
    """Book the verified G-code estimate after a continuously observed print.

    This path only covers prints without observed feeder or mapping changes.
    It does not identify an untagged spool or prove physical weight.
    """
    if not isinstance(evidence, dict) or evidence.get('complete') is not True or evidence.get('continuous') is not True:
        raise ValueError('Complete uninterrupted observation required')
    feed, tags, start, profile = (evidence.get(k) for k in ('feed', 'tags', 'start', 'profile'))
    if not isinstance(feed, dict) or feed.get('valid') is not True:
        raise ValueError('Feeder evidence unavailable')
    for field, expected in (('covered', True), ('runouts', False), ('insertions', False)):
        values = feed.get(field)
        if not isinstance(values, list) or len(values) != 4 or any(type(v) is not bool or v != expected for v in values):
            raise ValueError('Feeder continuity not established')
    if (not isinstance(tags, dict) or tags.get('known') is not True
            or tags.get('unchanged') != [True] * 4 or not isinstance(tags.get('initial'), list)
            or len(tags['initial']) != 4):
        raise ValueError('Spool tag continuity not established')
    if not isinstance(start, dict) or not isinstance(profile, dict) or evidence.get('mapping_unchanged') is not True:
        raise ValueError('Start or mapping evidence unavailable')
    def change(db):
        printer, initial_printer = db.get('printer', {}), start.get('printer', {})
        if (not printer.get('enabled') or not isinstance(initial_printer, dict)
                or (printer.get('host'), printer.get('port')) != (initial_printer.get('host'), initial_printer.get('port'))):
            raise ValueError('Printer connection changed')
        run = db['runs'].get(key)
        if not isinstance(run, dict):
            raise ValueError('Print job not recorded')
        if run['status'] == 'committed':
            return False
        if run['status'] != 'review' or run.get('terminal_status') != 'completed' or run.get('replenishment_observed'):
            raise ValueError('Print is not an eligible completed job')
        if run.get('review_reason') != 'Automatic replenishment cannot be ruled out; initial spool and estimate saved for review':
            raise ValueError('Print requires review for another reason')
        if (profile.get('filename') != run['filename'] or type(profile.get('started_at')) not in (int, float)
                or not math.isfinite(profile['started_at']) or abs(profile['started_at'] - run['start_time']) > .01
                or profile.get('mapping') != run.get('tool_mapping')):
            raise ValueError('G-code profile does not match job')
        slots, weights = run.get('physical_spool_ids'), run.get('physical_weights')
        if (not isinstance(slots, list) or len(slots) != 4 or not isinstance(weights, list) or len(weights) != 4
                or not isinstance(start.get('slots'), dict)
                or [start['slots'].get(str(i + 1)) for i in range(4)] != slots
                or physical_weights(profile.get('logical_weights'), profile.get('mapping')) != weights):
            raise ValueError('Spool or G-code estimate mismatch')
        amounts = {}
        for i, grams in enumerate(weights):
            if not grams:
                continue
            spool_id = slots[i]
            spool = db['spools'].get(spool_id)
            old = start.get('spools', {}).get(spool_id)
            if (not spool_id or not isinstance(spool, dict) or not isinstance(old, dict)
                    or db['slots'].get(str(i + 1)) != spool_id or spool_id in amounts
                    or old.get('remaining_g') != spool.get('remaining_g') or grams > spool['remaining_g']):
                raise ValueError('Spool assignment or balance changed')
            bound = spool.get('calibration', {}).get('uid')
            if bound and tags['initial'][i] != bound:
                raise ValueError('Spool tag does not match assignment')
            amounts[spool_id] = grams
        if not amounts:
            raise ValueError('No known G-code consumption')
        book(db, key, amounts)
        run['status'] = 'committed'
        _set_plan_status(db['plans'][run['plan_id']], 'committed')
        return True
    return store.update(change)


def commit_stream_estimate(store, key, evidence):
    """Book a guarded experimental stream estimate once, or leave review intact.

    Slot identity for untagged spools is user-assigned and remains an assumption;
    lengths and density are estimates. The stream must cover the whole job and
    agree with U1's aggregate counter. No printer controls are sent.
    """
    from motion_allocation import provisional_allocation
    if not isinstance(evidence, dict) or evidence.get('complete') is not True or evidence.get('continuous') is not True:
        raise ValueError('Complete uninterrupted motion evidence required')
    comparison = evidence.get('comparison')
    if not isinstance(comparison, dict) or comparison.get('matches') is not True:
        raise ValueError('Motion differs from printer total')
    feed = evidence.get('feed')
    if not isinstance(feed, dict) or feed.get('valid') is not True:
        raise ValueError('Feeder evidence unavailable')
    for field in ('covered', 'insertions'):
        if not isinstance(feed.get(field), list) or len(feed[field]) != 4 or any(type(v) is not bool for v in feed[field]):
            raise ValueError('Feeder evidence incomplete')
    tags = evidence.get('tags')
    if (not isinstance(tags, dict) or tags.get('known') is not True
            or not isinstance(tags.get('unchanged'), list) or len(tags['unchanged']) != 4
            or not isinstance(tags.get('initial'), list) or len(tags['initial']) != 4
            or any(type(v) is not bool for v in tags['unchanged'])):
        raise ValueError('Tag snapshot unavailable')
    heads, start, profile = evidence.get('heads'), evidence.get('start'), evidence.get('profile')
    if not isinstance(heads, list) or len(heads) != 4 or not isinstance(start, dict) or not isinstance(profile, dict):
        raise ValueError('Motion or spool snapshot unavailable')
    for i, item in enumerate(heads):
        if not isinstance(item, dict) or item.get('head') != i:
            raise ValueError('Physical head data invalid')
        length = item.get('net_mm')
        if isinstance(length, bool) or not isinstance(length, (float, int)) or not math.isfinite(length) or length < 0:
            raise ValueError('Physical head length invalid')
        if length > 0 and (not feed['covered'][i] or feed['insertions'][i] or not tags['unchanged'][i]):
            raise ValueError('Spool continuity cannot be assumed')
    total = comparison.get('printer_total_mm')
    if (isinstance(total, bool) or not isinstance(total, (float, int)) or not math.isfinite(total)
            or total <= 0 or abs(math.fsum(item['net_mm'] for item in heads) - total) > 0.102):
        raise ValueError('Motion differs from printer total')
    capture_id, epoch = evidence.get('capture_id'), evidence.get('epoch')
    if any(not isinstance(x, str) or not x or len(x) > 128 for x in (capture_id, epoch)):
        raise ValueError('Capture identity unavailable')
    def change(db):
        selected = db.get('printer', {})
        started_printer = start.get('printer', {})
        if (not selected.get('enabled') or not isinstance(started_printer, dict)
                or selected.get('host') != started_printer.get('host')
                or selected.get('port') != started_printer.get('port')):
            raise ValueError('Printer connection changed')
        run = db['runs'].get(key)
        if not isinstance(run, dict):
            raise ValueError('Print job not recorded')
        if run['status'] == 'committed' and run.get('accounting_method') == 'motion_estimate':
            if run.get('motion_capture_id') == capture_id and run.get('motion_epoch') == epoch:
                return False
            raise ValueError('Job already committed')
        if not ((run['status'] == 'review' and run.get('terminal_status') in ('completed', 'cancelled'))
                or (run['status'] == 'cancelled' and run.get('terminal_status') == 'cancelled')):
            raise ValueError('Print is not a completed or cancelled review job')
        if (profile.get('filename') != run['filename'] or
                isinstance(profile.get('started_at'), bool) or not isinstance(profile.get('started_at'), (float, int)) or
                not math.isfinite(profile['started_at']) or abs(profile['started_at'] - run['start_time']) > 0.01):
            raise ValueError('Verified profile does not match print job')
        if (not isinstance(start.get('slots'), dict)
                or [start['slots'].get(str(i + 1)) for i in range(4)] != run.get('physical_spool_ids')
                or profile.get('mapping') != run.get('tool_mapping')):
            raise ValueError('Captured spools or mapping do not match print start')
        for other_key, other in db['runs'].items():
            if other_key != key and other.get('motion_capture_id') == capture_id and other.get('motion_epoch') == epoch:
                raise ValueError('Capture belongs to another print')
        entries = provisional_allocation(heads, start, db, profile)
        if not entries or any(item.get('estimated_g') is None or item['estimated_g'] <= 0 for item in entries):
            raise ValueError('Estimated weight unavailable')
        for item in entries:
            spool = db['spools'][item['spool_id']]
            bound = spool.get('calibration', {}).get('uid')
            if bound and tags['initial'][item['head']] != bound:
                raise ValueError('Scanned tag does not match assigned spool')
        amounts = {item['spool_id']: item['estimated_g'] for item in entries}
        if len(amounts) != len(entries):
            raise ValueError('Spool appears in more than one head')
        for spool_id, grams in amounts.items():
            if start.get('spools', {}).get(spool_id, {}).get('remaining_g') != db['spools'][spool_id]['remaining_g']:
                raise ValueError('Spool balance changed during print')
            if grams > db['spools'][spool_id]['remaining_g']:
                raise ValueError('Estimated weight exceeds recorded balance')
        book(db, key, amounts)
        run.update({'status': 'committed', 'accounting_method': 'motion_estimate',
                    'motion_consumption': amounts, 'motion_capture_id': capture_id, 'motion_epoch': epoch})
        _set_plan_status(db['plans'][run['plan_id']], 'committed')
        return True
    return store.update(change)
