"""Full HTTP simulator -> production Moonraker client -> inventory path."""

import hashlib
import json
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from dev.mock_u1 import SAMPLES, create_server
from moonraker import MoonrakerClient, poll_once
from storage import Store
import spool_tracker


@pytest.fixture
def rig(tmp_path, monkeypatch):
    state_path = tmp_path / "printer-state.json"
    server, simulator = create_server(state_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    store = Store(tmp_path / "tracker-data")
    store.read()

    def seed(db):
        db["printer"].update({"enabled": True, "host": "127.0.0.1", "port": server.server_port})
        for index in range(4):
            spool_id = f"spool{index}"
            db["spools"][spool_id] = {"name": spool_id, "material": "PLA", "remaining_g": 1000.0}
            db["slots"][str(index + 1)] = spool_id

    store.update(seed)
    monkeypatch.setattr(spool_tracker, "STORE", store)
    monkeypatch.delenv("SLIC3R_PP_OUTPUT_NAME", raising=False)

    class Rig:
        def __init__(self):
            self.server = server
            self.thread = thread
            self.simulator = simulator
            self.store = store
            self.state_path = state_path

        @property
        def port(self):
            return self.server.server_port

        def control(self, action, **fields):
            request = Request(f"http://127.0.0.1:{self.port}/control/{action}",
                              data=urlencode(fields).encode("utf-8"), method="POST")
            with urlopen(request, timeout=3) as response:
                assert response.status == 200  # 303 redirected to the control page.

        def poll(self, store=None):
            poll_once(store or self.store)

        def plan(self, filename):
            path = SAMPLES / filename
            assert spool_tracker.handle_slicer_hook(path) == 0
            return next(reversed(self.store.read()["plans"]))

        def remaining(self):
            db = self.store.read()
            return [db["spools"][f"spool{i}"]["remaining_g"] for i in range(4)]

        def stop(self):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)

        def restart(self):
            port = self.port
            self.stop()
            self.server, self.simulator = create_server(self.state_path, port)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

    test_rig = Rig()
    try:
        yield test_rig
    finally:
        if test_rig.thread.is_alive():
            test_rig.stop()


def test_simulator_serves_stock_shapes_and_real_file_bytes(rig):
    rig.control("select", filename="four_tool.gcode")
    client = MoonrakerClient("127.0.0.1", rig.port)
    assert client.status() == {"connected": True, "state": "standby", "filename": "", "klippy_state": "ready"}
    assert client.history() == []
    payload = (SAMPLES / "four_tool.gcode").read_bytes()
    assert client.fingerprint("four_tool.gcode") == (hashlib.sha256(payload).hexdigest(), len(payload))
    with urlopen(f"http://127.0.0.1:{rig.port}/server/files/metadata?filename=four_tool.gcode") as response:
        metadata = json.load(response)["result"]
    assert metadata["filename"] == "four_tool.gcode"
    assert metadata["size"] == len(payload)


def test_control_page_disconnect_and_restart(rig):
    with urlopen(f"http://127.0.0.1:{rig.port}/") as response:
        page = response.read().decode("utf-8")
    assert "Current state: <strong>IDLE</strong>" in page
    assert "Start Print" in page and "Disconnect / Stop Server" in page
    rig.control("disconnect")
    rig.thread.join(timeout=3)
    assert not rig.thread.is_alive()
    rig.restart()
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "standby"


def test_orca_post_processing_temp_file_matches_remote_filename(rig, tmp_path):
    temporary = tmp_path / "orca.gcode.pp"
    temporary.write_bytes((SAMPLES / "single_tool.gcode").read_bytes())
    assert spool_tracker.handle_slicer_hook(temporary) == 0
    plan = next(iter(rig.store.read()["plans"].values()))
    assert plan["filename"] == "orca.gcode"
    rig.control("select", path=str(temporary))
    rig.control("start")
    rig.poll()
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [900, 1000, 1000, 1000]


def test_plan_start_complete_duplicate_and_reconnect(rig):
    plan_id = rig.plan("single_tool.gcode")
    rig.control("select", filename="single_tool.gcode")
    rig.poll()  # A: idle with a plan does not debit.
    assert rig.store.read()["plans"][plan_id]["status"] == "planned"
    assert rig.remaining() == [1000] * 4

    rig.control("start")
    client = MoonrakerClient("127.0.0.1", rig.port)
    assert client.status()["state"] == "printing"
    assert client.history()[-1]["status"] == "in_progress"
    rig.poll()  # B: print start marks active, without consuming.
    assert rig.store.read()["plans"][plan_id]["status"] == "active"
    assert rig.remaining() == [1000] * 4

    rig.control("complete")
    assert client.status()["state"] == "complete"
    assert client.history()[-1]["status"] == "completed"
    rig.poll()  # C: completion consumes once.
    assert rig.remaining() == [900, 1000, 1000, 1000]
    rig.control("complete")  # D: same event remains the same job.
    rig.poll()
    assert rig.remaining() == [900, 1000, 1000, 1000]

    rig.restart()  # E: both sides recover from persisted state.
    restarted_tracker = Store(rig.store.directory)
    rig.poll(restarted_tracker)
    assert rig.remaining() == [900, 1000, 1000, 1000]
    assert len(rig.store.read()["runs"]) == 1


@pytest.mark.parametrize("action,expected", [("cancel", "cancelled"), ("error", "error")])
def test_cancel_and_error_never_debit(rig, action, expected):
    plan_id = rig.plan("two_tool.gcode")
    rig.control("select", filename="two_tool.gcode")
    rig.control("start")
    rig.poll()
    rig.control(action)
    assert MoonrakerClient("127.0.0.1", rig.port).history()[-1]["status"] == expected
    rig.poll()
    assert rig.remaining() == [1000] * 4
    assert rig.store.read()["plans"][plan_id]["status"] == expected


def test_unrelated_filename_and_same_name_different_bytes_do_not_debit(rig, tmp_path):
    plan_id = rig.plan("single_tool.gcode")
    rig.control("select", filename="unrelated.gcode")
    rig.control("start")
    rig.control("complete")
    rig.poll()  # H: a different filename does not match.
    assert rig.remaining() == [1000] * 4

    changed = tmp_path / "other" / "single_tool.gcode"
    changed.parent.mkdir()
    changed.write_bytes(b"; filament used [g] = 100, 0, 0, 0\n; changed bytes\n")
    rig.control("select", path=str(changed), filename="single_tool.gcode")
    rig.control("start")
    rig.control("complete")
    rig.poll()  # I: the right filename with a different hash does not match.
    assert rig.remaining() == [1000] * 4
    assert rig.store.read()["plans"][plan_id]["status"] == "planned"
    assert not rig.store.read()["runs"]


def test_four_tool_uses_spools_captured_before_reassignment(rig):
    plan_id = rig.plan("four_tool.gcode")

    def reassign(db):
        db["spools"]["replacement"] = {"name": "replacement", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "replacement"

    rig.store.update(reassign)
    rig.control("select", filename="four_tool.gcode")
    rig.control("start")
    rig.poll()
    rig.control("complete")
    rig.poll()  # J/K: charge the four original spool IDs, not replacement.
    assert rig.remaining() == [990, 980, 970, 960]
    assert rig.store.read()["spools"]["replacement"]["remaining_g"] == 1000
    assert rig.store.read()["plans"][plan_id]["spool_ids"] == ["spool0", "spool1", "spool2", "spool3"]


def test_repeated_exports_and_disconnected_printer_leave_inventory_untouched(rig):
    for _ in range(3):
        rig.plan("single_tool.gcode")
    rig.poll()  # L: three planned exports, zero physical jobs.
    assert rig.remaining() == [1000] * 4
    assert len(rig.store.read()["plans"]) == 3

    rig.stop()
    rig.poll()  # M: connection failure cannot consume a plan.
    assert rig.remaining() == [1000] * 4
    assert rig.store.read()["monitor"]["state"] == "disconnected"
    assert not rig.store.read()["monitor"]["connected"]


def test_tracker_restart_after_start_before_completion(rig):
    rig.plan("single_tool.gcode")
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    rig.control("complete")
    rig.poll(Store(rig.store.directory))
    assert rig.remaining() == [900, 1000, 1000, 1000]
    rig.poll(Store(rig.store.directory))
    assert rig.remaining() == [900, 1000, 1000, 1000]
