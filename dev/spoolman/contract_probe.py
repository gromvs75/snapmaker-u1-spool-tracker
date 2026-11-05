#!/usr/bin/env python3
"""Probe pinned upstream Spoolman on a disposable local database, never a user URL.

Requires the upstream locked environment and prebuilt official client assets.
Uses only Python stdlib in the controlling process. No Tracker imports/settings.
"""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PIN = "ff8efd517b76a4b2783f29c89e9b9fbcd8cd167b"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--tracker', action='store_true', help='Also exercise Tracker against this disposable server')
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if commit != PIN:
        raise SystemExit("Refusing unpinned upstream checkout")
    if subprocess.check_output(["git", "diff", "HEAD", "--", "spoolman", "migrations",
                                "pyproject.toml", "uv.lock"], cwd=upstream):
        raise SystemExit("Refusing modified upstream server code")
    python = upstream / ".venv/bin/python"
    report = {"version": "0.27.1", "commit": commit, "checks": [],
              "scope": "Disposable SQLite; loopback only; no printer; no Tracker data",
              "lock_sha256": hashlib.sha256((upstream / "uv.lock").read_bytes()).hexdigest()}

    def check(name, condition, **evidence):
        report["checks"].append(dict(name=name, passed=bool(condition), **evidence))
        if not condition:
            raise AssertionError(name + ": " + repr(evidence))

    def request(port, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, "/api/v1" + path,
                         None if body is None else json.dumps(body),
                         {"Content-Type": "application/json", **(headers or {})})
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None, dict(response.headers)
        finally:
            conn.close()

    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tracker-spoolman-probe-") as temp:
        # Do not inherit database credentials, proxy or Spoolman settings from the host.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SPOOLMAN_", "EXTERNAL_DB_", "PYTHON"))
               and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env.update(SPOOLMAN_DIR_DATA=temp + "/data", SPOOLMAN_DIR_LOGS=temp + "/logs",
                   SPOOLMAN_DIR_BACKUPS=temp + "/backups", SPOOLMAN_DB_TYPE="sqlite",
                   SPOOLMAN_AUTOMATIC_BACKUP="FALSE", SPOOLMAN_UPDATE_CHECK="FALSE",
                   EXTERNAL_DB_URL="", PATH=str(python.parent) + os.pathsep + os.defpath)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        process = None
        try:
            with (args.output / "server.log").open("w") as log:
                process = subprocess.Popen(
                    [str(python), "-m", "uvicorn", "spoolman.main:app", "--fd",
                     str(listener.fileno()), "--no-access-log"], cwd=upstream, env=env,
                    pass_fds=(listener.fileno(),), stdout=log, stderr=subprocess.STDOUT)
                listener.close()
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Spoolman exited; inspect server.log")
                    try:
                        if request(port, "GET", "/health")[0] == 200:
                            break
                    except (OSError, http.client.HTTPException):
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Spoolman startup")
                    time.sleep(.1)
                status, info, _ = request(port, "GET", "/info")
                check("isolated_server", status == 200 and info["version"] == "0.27.1"
                      and Path(info["data_dir"]).resolve().is_relative_to(Path(temp).resolve()),
                      version=info.get("version"), status=status)
                status, schema, _ = request(port, "GET", "/openapi.json")
                check("openapi", status == 200)
                (args.output / "openapi.json").write_text(json.dumps(schema, indent=2))
                params = schema["components"]["schemas"]["SpoolUseParameters"]["properties"]
                check("use_has_no_operation_id", set(params) == {"use_weight", "use_length"},
                      fields=list(params))

                status, filament, _ = request(port, "POST", "/filament", {
                    "name": "Tracker disposable PLA", "material": "PLA", "density": 1.24,
                    "diameter": 1.75, "weight": 1000, "color_hex": "ffffff"})
                check("create_filament", status == 200, status=status)

                def new_spool(**overrides):
                    s, item, _ = request(port, "POST", "/spool", {
                        "filament_id": filament["id"], "initial_weight": 1000,
                        "spool_weight": 200, **overrides})
                    check("create_spool", s == 200, status=s)
                    return item

                item = new_spool()
                path = "/spool/" + str(item["id"])
                status, page, headers = request(port, "GET", "/spool?limit=1&offset=0")
                check("catalog_pagination", status == 200 and len(page) == 1
                      and any(k.lower() == "x-total-count" for k in headers))
                status, first, _ = request(port, "PUT", path + "/use", {"use_weight": 12.345},
                                           {"Idempotency-Key": "tracker-same-operation"})
                status2, second, _ = request(port, "PUT", path + "/use", {"use_weight": 12.345},
                                            {"Idempotency-Key": "tracker-same-operation"})
                check("same_key_deducts_twice", status == status2 == 200
                      and abs(second["used_weight"] - 24.69) < 1e-8,
                      first=first["used_weight"], second=second["used_weight"])

                status, _, _ = request(port, "PUT", path + "/use",
                                       {"use_weight": 1, "use_length": 1})
                check("mixed_units_rejected", status == 400, status=status)
                status, _, _ = request(port, "GET", "/spool/99999999")
                check("missing_spool", status == 404, status=status)
                before = request(port, "GET", path)[1]["used_weight"]
                status, _, _ = request(port, "PUT", path + "/use", {"use_weight": 50},
                                       {"Origin": "https://untrusted.invalid"})
                check("origin_denied_without_mutation", status == 403
                      and request(port, "GET", path)[1]["used_weight"] == before, status=status)

                # One-shot loopback proxy waits for a successful server response, then
                # closes the client connection without forwarding any response bytes.
                observed = {}

                class DropResponse(BaseHTTPRequestHandler):
                    def do_PUT(self):
                        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        observed["upstream"] = request(port, "PUT", path + "/use", body)[0]
                        self.close_connection = True

                    def log_message(self, *unused):
                        pass

                proxy = ThreadingHTTPServer(("127.0.0.1", 0), DropResponse)
                worker = threading.Thread(target=proxy.serve_forever, daemon=True)
                worker.start()
                try:
                    lost = False
                    try:
                        request(proxy.server_port, "PUT", path + "/use", {"use_weight": 10})
                    except (OSError, http.client.HTTPException):
                        lost = True
                    after = request(port, "GET", path)[1]["used_weight"]
                    check("lost_response_but_committed", lost and observed.get("upstream") == 200
                          and abs(after - before - 10) < 1e-8, before=before, after=after)
                    # Deliberately unsafe retry to demonstrate the failure on fake inventory.
                    retried = request(port, "PUT", path + "/use", {"use_weight": 10})[1]
                    check("blind_retry_double_charges", abs(retried["used_weight"] - after - 10) < 1e-8,
                          after_retry=retried["used_weight"])
                finally:
                    proxy.shutdown()
                    proxy.server_close()
                    worker.join()

                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(lambda _: request(port, "PUT", path + "/use",
                                                             {"use_weight": 1})[0], range(8)))
                final = request(port, "GET", path)[1]
                check("concurrent_deltas_preserved", all(s == 200 for s in results)
                      and abs(final["used_weight"] - retried["used_weight"] - 8) < 1e-8)
                over = new_spool(initial_weight=5)
                value = request(port, "PUT", f'/spool/{over["id"]}/use', {"use_weight": 8})[1]
                check("overdraw_retains_usage_clamps_remaining", value["used_weight"] == 8
                      and value["remaining_weight"] == 0, result=value)
                status, unknown_filament, _ = request(port, "POST", "/filament", {
                    "name": "Unknown weight", "density": 1.24, "diameter": 1.75})
                status, unknown, _ = request(port, "POST", "/spool", {"filament_id": unknown_filament["id"]})
                check("unknown_remaining_omitted", status == 200 and "remaining_weight" not in unknown)
                archived = new_spool(archived=True)
                status, value, _ = request(port, "PUT", f'/spool/{archived["id"]}/use', {"use_weight": 1})
                check("archived_write_not_blocked_by_server", status == 200 and value["used_weight"] == 1)
                if args.tracker:
                    import sys
                    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
                    from spoolman_bridge import Bridge, remote_id
                    from storage import Store
                    from accounting import create_plan, apply_history_job, fingerprint_file
                    from backup import create_backup, import_backup
                    tracker_store = Store(Path(temp) / 'tracker')
                    bridge = Bridge(tracker_store)
                    base_url = 'http://127.0.0.1:%d' % port
                    bridge.configure(base_url, 'send', True)
                    fresh = new_spool()
                    bridge.attach(fresh['id'], 0)
                    local_id = remote_id(base_url, fresh['id'])
                    tracker_store.update(lambda db: db['printer'].update(enabled=True))
                    gcode = Path(temp) / 'test.gcode'
                    gcode.write_text('; test')
                    create_plan(tracker_store, gcode, 'test.gcode', [20, 0, 0, 0], tracker_store.read(), now=999)
                    config = tracker_store.read()['printer']
                    job = {'job_id': 'fake-job-1', 'filename': 'test.gcode', 'start_time': 1000, 'status': 'in_progress'}
                    apply_history_job(tracker_store, config, job, fingerprint_file(gcode),
                                      {'mapping': [0, 1, 2, 3], 'auto_replenish': False})
                    job['status'] = 'completed'
                    apply_history_job(tracker_store, config, job)
                    old_backup = Path(temp) / 'tracker-backup.json'
                    old_backup.write_text(json.dumps(create_backup(tracker_store, 'preview')))
                    check('tracker_queues_without_local_debit', tracker_store.read()['spools'][local_id]['remaining_g'] == 1000
                          and len(tracker_store.read()['spoolman']['outbox']) == 1)
                    bridge.send_one()
                    apply_history_job(tracker_store, config, job)
                    bridge.send_one()
                    real = request(port, 'GET', '/spool/%d' % fresh['id'])[1]
                    check('tracker_real_server_exactly_one_normal_send', real['used_weight'] == 20
                          and tracker_store.read()['spools'][local_id]['remaining_g'] == 980)
                    import_backup(tracker_store, old_backup)
                    bridge.send_one()
                    check('tracker_restore_does_not_replay', request(port, 'GET', '/spool/%d' % fresh['id'])[1]['used_weight'] == 20
                          and tracker_store.read()['spoolman']['mode'] == 'off')
                report["native_auth"] = "No credentials required for tested loopback REST API; 403 test is origin guard, not user authentication."
        finally:
            listener.close()
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            # Port is closed: distinguish definite unavailability from lost response.
            try:
                request(port, "GET", "/health")
            except (OSError, http.client.HTTPException):
                report["server_stopped"] = True
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": sum(c["passed"] for c in report["checks"]),
                      "total": len(report["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
