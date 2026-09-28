"""Read-only client and polling monitor for stock U1 Moonraker."""
import hashlib
import json
import logging
import threading
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, build_opener

from accounting import apply_history_job, file_name, run_key

LOGGER = logging.getLogger("snapmaker_tracker")


class MoonrakerError(Exception):
    pass


class MoonrakerClient:
    def __init__(self, host, port, timeout=5, opener=None):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
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

    def status(self):
        result = self._json("/printer/objects/query?webhooks&print_stats")
        try:
            objects = result["status"]
            return {"connected": True, "state": objects["print_stats"]["state"],
                    "filename": objects["print_stats"].get("filename", ""),
                    "klippy_state": objects["webhooks"]["state"]}
        except (KeyError, TypeError) as exc:
            raise MoonrakerError("Moonraker print_stats/webhooks are unavailable") from exc

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


def _set_status(store, connected, state, filename="", error=""):
    import time
    store.update(lambda db: db.__setitem__("monitor", {
        "connected": connected, "state": state, "filename": filename,
        "error": error[:500], "checked_at": time.time()
    }))


def poll_once(store, client_factory=MoonrakerClient):
    snapshot = store.read()
    config = snapshot["printer"]
    if not config["enabled"]:
        if snapshot["monitor"]["state"] != "disabled":
            _set_status(store, False, "disabled")
        return
    client = client_factory(config["host"], config["port"])
    try:
        current = client.status()
        jobs = client.history()
    except Exception as exc:
        LOGGER.warning("Moonraker unavailable: %s", exc)
        _set_status(store, False, "disconnected", error=str(exc))
        return
    _set_status(store, True, current["state"], current["filename"],
                "" if current["klippy_state"] == "ready" else f'Klippy: {current["klippy_state"]}')
    fingerprints = {}
    known_runs = set(snapshot["runs"])
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("filename"), str):
            continue
        if not isinstance(job.get("job_id"), str) or not isinstance(job.get("start_time"), (int, float)):
            continue
        key = run_key(config, job)
        remote = None
        if key not in known_runs:
            name = file_name(job["filename"]).casefold()
            if not any(plan["filename"].casefold() == name
                       and plan["printer"]["host"].casefold() == config["host"].casefold()
                       and plan["printer"]["port"] == config["port"]
                       for plan in snapshot["plans"].values()):
                continue
            if job["filename"] not in fingerprints:
                try:
                    fingerprints[job["filename"]] = client.fingerprint(job["filename"])
                except Exception as exc:
                    LOGGER.warning("Cannot verify remote G-code %s: %s", job["filename"], exc)
                    continue
            remote = fingerprints[job["filename"]]
        result = apply_history_job(store, config, job, remote)
        if result:
            known_runs.add(key)
            LOGGER.info("Printer job %s: %s", job["job_id"], result)


class PrinterMonitor:
    def __init__(self, store, interval=10):
        self.store = store
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="printer-monitor")
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                poll_once(self.store)
            except Exception:
                LOGGER.exception("Printer monitor error")
            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)
