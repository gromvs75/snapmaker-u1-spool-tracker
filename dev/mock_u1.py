#!/usr/bin/env python3
"""Local development-only Moonraker subset for testing spool accounting."""

import argparse
import html
import json
import os
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "sample_gcodes"
DEFAULT_STATE = HERE / ".mock_u1_state.json"
HOST = "127.0.0.1"
PORT = 7126


class SimulatorError(ValueError):
    pass


def _filename(value):
    name = str(value).replace("\\", "/")
    if not name or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
        raise SimulatorError("Invalid Moonraker filename")
    if not name.lower().endswith(".gcode"):
        raise SimulatorError("Choose a .gcode file")
    return name


class MockU1:
    def __init__(self, state_path=DEFAULT_STATE, samples=SAMPLES):
        self.state_path = Path(state_path)
        self.samples = Path(samples)
        self.lock = threading.RLock()
        if self.state_path.exists():
            self.data = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.data = {"files": {}, "selected": "", "state": "standby",
                         "current_filename": "", "history": []}
        for path in sorted(self.samples.glob("*.gcode")):
            self.data["files"].setdefault(path.name, str(path.resolve()))
        if not self.data["selected"] and self.data["files"]:
            self.data["selected"] = next(iter(self.data["files"]))

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def select(self, path, filename=""):
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise SimulatorError("G-code file does not exist")
        source_name = source.name
        if not (source_name.lower().endswith(".gcode")
                or source_name.lower().endswith(".gcode.pp")):
            raise SimulatorError("Choose a local .gcode or .gcode.pp file")
        default_name = source_name[:-3] if source_name.lower().endswith(".pp") else source_name
        name = _filename(filename or default_name)
        with self.lock:
            if self.data["state"] == "printing":
                raise SimulatorError("Finish the current print before changing files")
            self.data["files"][name] = str(source)
            self.data["selected"] = name
            self._save()
        return name

    def select_known(self, filename):
        name = _filename(filename)
        with self.lock:
            path = self.data["files"].get(name)
        if not path:
            raise SimulatorError("Unknown G-code file")
        return self.select(path, name)

    def file_path(self, filename):
        name = _filename(filename)
        with self.lock:
            source = self.data["files"].get(name)
        if not source or not Path(source).is_file():
            raise SimulatorError("G-code file is unavailable")
        return Path(source)

    def start(self):
        with self.lock:
            if self.data["state"] == "printing":
                raise SimulatorError("A print is already active")
            name = self.data["selected"]
            self.file_path(name)
            now = time.time()
            self.data["history"].append({"job_id": uuid.uuid4().hex,
                                         "filename": name, "status": "in_progress",
                                         "start_time": now, "end_time": None,
                                         "print_duration": 0.0})
            self.data["state"] = "printing"
            self.data["current_filename"] = name
            self._save()

    def finish(self, state):
        if state not in ("complete", "cancelled", "error"):
            raise SimulatorError("Invalid terminal print state")
        with self.lock:
            if self.data["state"] == state:
                return  # Repeated Complete/Cancel/Error is the same printer job.
            if self.data["state"] != "printing":
                raise SimulatorError("No active print")
            job = self.data["history"][-1]
            job["status"] = "completed" if state == "complete" else state
            job["end_time"] = time.time()
            job["print_duration"] = max(0.0, job["end_time"] - job["start_time"])
            self.data["state"] = state
            self._save()

    def idle(self):
        with self.lock:
            if self.data["state"] == "printing":
                raise SimulatorError("Cancel or complete the active print first")
            self.data["state"] = "standby"
            self.data["current_filename"] = ""
            self._save()

    def status(self):
        with self.lock:
            duration = 0.0
            if self.data["history"] and self.data["current_filename"]:
                job = self.data["history"][-1]
                duration = (max(0.0, time.time() - job["start_time"])
                            if job["status"] == "in_progress" else job["print_duration"])
            return {"webhooks": {"state": "ready"},
                    "print_stats": {"state": self.data["state"],
                                    "filename": self.data["current_filename"],
                                    "print_duration": duration}}

    def history(self, start=0, limit=50, order="desc"):
        with self.lock:
            jobs = list(self.data["history"])
        jobs.sort(key=lambda job: job["start_time"], reverse=order == "desc")
        return {"count": len(jobs), "jobs": jobs[start:start + limit]}

    def view(self):
        with self.lock:
            return {"state": self.data["state"], "selected": self.data["selected"],
                    "current_filename": self.data["current_filename"],
                    "files": dict(self.data["files"]),
                    "history": list(reversed(self.data["history"][-20:]))}


def _page(view):
    esc = html.escape
    state_label = "IDLE" if view["state"] == "standby" else view["state"].upper()
    options = "".join(f'<option value="{esc(name, quote=True)}" '
                      f'{"selected" if name == view["selected"] else ""}>{esc(name)}</option>'
                      for name in view["files"])
    history = "".join(f'<li>{esc(job["filename"])} — {esc(job["status"])} '
                      f'({esc(job["job_id"][:8])})</li>' for job in view["history"])
    buttons = "".join(f'<form method="post" action="/control/{action}">'
                      f'<button type="submit">{label}</button></form>'
                      for action, label in (("idle", "Set Idle"), ("start", "Start Print"),
                                            ("complete", "Complete Print"), ("cancel", "Cancel Print"),
                                            ("error", "Error Print"), ("disconnect", "Disconnect / Stop Server")))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fake Snapmaker U1</title>
<style>body{{font:16px system-ui;max-width:700px;margin:2rem auto;padding:0 1rem}}
form{{display:inline-block;margin:.3rem}}fieldset{{margin:1rem 0;padding:1rem}}
input{{max-width:100%;box-sizing:border-box}}button{{padding:.5rem .8rem;cursor:pointer}}</style>
<h1>Fake Snapmaker U1</h1><p>Connection: <strong>ONLINE</strong></p>
<p>Current state: <strong>{esc(state_label)}</strong></p>
<p>Current file: <strong>{esc(view["current_filename"] or "—")}</strong></p>
<fieldset><legend>Select an available G-code</legend>
<form method="post" action="/control/select"><select name="filename">{options}</select>
<button type="submit">Select file</button></form></fieldset>
<fieldset><legend>Use an Orca-exported local file</legend>
<form method="post" action="/control/select"><label>Full file path <input name="path" size="50" required></label><br>
<label>Printer filename (optional) <input name="filename" size="35" placeholder="defaults to basename"></label>
<button type="submit">Use this file</button></form></fieldset>
<p>Selected for next print: <strong>{esc(view["selected"] or "—")}</strong></p>
<div>{buttons}</div><h2>History</h2><ul>{history or "<li>No jobs yet</li>"}</ul>
<p>Moonraker API is available at this same address. Local development only.</p></html>'''


def make_handler(simulator):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            print("mock_u1:", format % args)

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, result):
            self._send(HTTPStatus.OK, json.dumps({"result": result}).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _error(self, status, message):
            self._send(status, json.dumps({"error": message}).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _local_request(self):
            authority = self.headers.get("Host", "").split(":", 1)[0]
            return authority == HOST

        def do_GET(self):
            if not self._local_request():
                self._error(HTTPStatus.FORBIDDEN, "Localhost only")
                return
            url = urlsplit(self.path)
            params = parse_qs(url.query, keep_blank_values=True)
            try:
                if url.path == "/":
                    self._send(HTTPStatus.OK, _page(simulator.view()).encode("utf-8"),
                               "text/html; charset=utf-8")
                elif url.path == "/printer/objects/query":
                    if not {"webhooks", "print_stats"}.issubset(params):
                        raise SimulatorError("Query webhooks and print_stats")
                    self._json({"status": simulator.status(), "eventtime": time.time()})
                elif url.path == "/server/history/list":
                    start = max(0, int(params.get("start", ["0"])[0]))
                    limit = min(500, max(0, int(params.get("limit", ["50"])[0])))
                    order = params.get("order", ["desc"])[0]
                    if order not in ("asc", "desc"):
                        raise SimulatorError("Invalid history order")
                    self._json(simulator.history(start, limit, order))
                elif url.path == "/server/files/metadata":
                    filename = params.get("filename", [""])[0]
                    source = simulator.file_path(filename)
                    stat = source.stat()
                    self._json({"filename": filename, "size": stat.st_size,
                                "modified": stat.st_mtime})
                elif url.path.startswith("/server/files/gcodes/"):
                    filename = unquote(url.path.removeprefix("/server/files/gcodes/"))
                    source = simulator.file_path(filename)
                    with source.open("rb") as stream:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(source.stat().st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        while chunk := stream.read(1024 * 1024):
                            self.wfile.write(chunk)
                else:
                    self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            except (SimulatorError, ValueError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except OSError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))

        def do_POST(self):
            if not self._local_request():
                self._error(HTTPStatus.FORBIDDEN, "Localhost only")
                return
            origin = self.headers.get("Origin")
            expected = f"http://{HOST}:{self.server.server_port}"
            if origin and origin != expected:
                self._error(HTTPStatus.FORBIDDEN, "Local origin required")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Form too large")
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            action = urlsplit(self.path).path
            try:
                if action == "/control/select":
                    filename = form.get("filename", [""])[0]
                    path = form.get("path", [""])[0]
                    if path:
                        simulator.select(path, filename)
                    else:
                        simulator.select_known(filename)
                elif action == "/control/idle":
                    simulator.idle()
                elif action == "/control/start":
                    simulator.start()
                elif action in ("/control/complete", "/control/cancel", "/control/error"):
                    simulator.finish(action.rsplit("/", 1)[-1].replace("cancel", "cancelled"))
                elif action == "/control/disconnect":
                    self._send(HTTPStatus.OK,
                               b"<h1>Fake Snapmaker U1 disconnected</h1><p>Restart the simulator to reconnect.</p>",
                               "text/html; charset=utf-8")
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    self._error(HTTPStatus.NOT_FOUND, "Unknown control")
                    return
            except (SimulatorError, OSError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def create_server(state_path=DEFAULT_STATE, port=PORT, samples=SAMPLES):
    simulator = MockU1(state_path, samples)
    server = ThreadingHTTPServer((HOST, port), make_handler(simulator))
    server.daemon_threads = True
    return server, simulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=PORT, help="local port (default: 7126)")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    server, _ = create_server(args.state_file, args.port)
    print(f"Fake Snapmaker U1: http://{HOST}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
