"""Planned G-code snapshots and idempotent physical-print accounting."""
import hashlib
import math
import time
import uuid


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


def apply_history_job(store, printer, job, remote_fingerprint=None):
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
        run = db["runs"].get(key)
        if run and run["status"] != "active":
            return run["status"]
        if run is None:
            candidates = _matching_plans(db, printer, job, remote_fingerprint)
            if not candidates:
                return None
            plan_id, plan = candidates[0]
            mappings = {(tuple(p["spool_ids"]), tuple(p["weights"])) for _, p in candidates}
            run = {"job_id": job["job_id"], "plan_id": plan_id,
                   "start_time": float(job["start_time"]), "status": "active",
                   "filename": job["filename"]}
            db["runs"][key] = run
            if len(mappings) > 1:
                run["status"] = "review"
                plan["status"] = "review"
                return "review"
            plan["status"] = "active"
        plan = db["plans"][run["plan_id"]]
        if status == "in_progress":
            return "active"
        if status == "completed":
            consumption = {}
            for spool_id, grams in zip(plan["spool_ids"], plan["weights"]):
                if grams > 0:
                    if not spool_id or spool_id not in db["spools"]:
                        run["status"] = plan["status"] = "review"
                        return "review"
                    consumption[spool_id] = consumption.get(spool_id, 0.0) + grams
            for spool_id, grams in consumption.items():
                spool = db["spools"][spool_id]
                spool["remaining_g"] = round(max(0.0, spool["remaining_g"] - grams), 3)
            run["status"] = plan["status"] = "committed"
            return "committed"
        run["status"] = plan["status"] = "cancelled" if status == "cancelled" else "error"
        return run["status"]

    return store.update(change)
