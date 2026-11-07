"""Full HTTP simulator -> production Moonraker client -> inventory path."""

import hashlib
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from dev.mock_u1 import SAMPLES, create_server
from moonraker import GuardRuntime, MoonrakerClient, MoonrakerError, PrinterMonitor, decide_guard, poll_once
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

        def poll(self, store=None, runtime=None, client_factory=MoonrakerClient):
            poll_once(store or self.store, client_factory=client_factory, guard_runtime=runtime)

        def wait_guard(self, state, timeout=3):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                guard = self.store.read().get("last_guard") or {}
                if guard.get("state") == state:
                    return guard
                threading.Event().wait(0.01)
            raise AssertionError(f"Guard did not reach {state}; got {guard}")

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


def test_accounted_print_retires_only_its_slice_forecast(rig, tmp_path):
    from forecast_service import ForecastService
    from dev.observer_fixture import payload
    folder = tmp_path / 'slices/session/Metadata'
    folder.mkdir(parents=True)
    source = folder / '.42.0.gcode'
    source.write_bytes(payload('0, 0, 16.69, 0'))
    service = ForecastService(rig.store, lambda: None, tmp_path / 'slices')
    service.poll(); service.observer.settle = 0; service.poll()
    assert len(service.snapshot()['entries']) == 1
    rig.control('select', path=str(source), filename='printed.gcode')
    rig.control('start'); rig.poll()
    assert service.snapshot()['printing']
    assert len(service.snapshot()['entries']) == 1
    rig.control('complete'); rig.poll()
    assert rig.remaining() == [1000, 1000, 983.31, 1000]
    assert service.snapshot()['entries'] == []
    rig.poll()
    assert rig.remaining()[2] == 983.31
    restarted = ForecastService(rig.store, lambda: None, tmp_path / 'slices')
    restarted.poll(); restarted.observer.settle = 0; restarted.poll()
    assert restarted.snapshot()['entries'] == []
    # Equal usage is not identity: a different model must retain its forecast.
    other = folder / '.42.1.gcode'
    other.write_bytes(payload('0, 0, 16.69, 0').replace(b'G1 X1', b'G1 X2'))
    restarted.poll(); restarted.poll()
    assert [e['source'] for e in restarted.snapshot()['entries']] == [str(other.relative_to(service.root))]
    # A new slice of the same bytes after the print is a new forecast.
    event = dict(service.state.entries[str(source.relative_to(service.root))], completed_at_ns=time.time_ns())
    restarted.state.accept([event])
    assert len(restarted.snapshot()['entries']) == 2


def test_accounted_forecast_clears_head_cards_in_browser(rig, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from forecast_service import ForecastService
    from dev.observer_fixture import payload
    folder = tmp_path / 'slices/session/Metadata'
    folder.mkdir(parents=True)
    source = folder / '.42.0.gcode'
    source.write_bytes(payload('0, 0, 16.69, 0'))
    service = ForecastService(rig.store, lambda: None, tmp_path / 'slices')
    service.poll(); service.observer.settle = 0; service.poll()
    rig.store.update(lambda db: db.update(language='ru'))
    rig.control('select', path=str(source), filename='printed.gcode')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            path = route.request.url.split('http://tracker.test', 1)[-1]
            if path == '/':
                route.fulfill(content_type='text/html', body=spool_tracker.HTML_PAGE)
            elif path == '/api/data':
                route.fulfill(json=rig.store.read())
            elif path == '/api/forecast':
                route.fulfill(json=service.snapshot())
            else:
                route.fulfill(json={})
        page.route('**/*', respond)
        try:
            page.goto('http://tracker.test/')
            head = page.locator('#sidebar-slots .sidebar-slot').nth(2)
            playwright.expect(head.locator('.forecast-head-note')).to_contain_text('983,31')
            rig.control('start'); rig.poll()
            page.evaluate('pollLive()')
            playwright.expect(head.locator('.forecast-head-note')).to_have_count(0)
            rig.control('complete'); rig.poll()
            # Exercise both independent refreshes, including the transient stale
            # forecast applied after the inventory has already updated.
            page.evaluate('pollLive()')
            page.evaluate('refreshSliceForecast()')
            playwright.expect(head.locator('.head-remaining')).to_contain_text('983.31')
            playwright.expect(page.locator('.forecast-head-note')).to_have_count(0)
            playwright.expect(page.locator('.forecast-head-icon')).to_have_count(0)
            playwright.expect(head.locator('.printhead-material')).to_have_text('PLA')
            page.evaluate('pollLive()')
            page.evaluate('refreshSliceForecast()')
            playwright.expect(head.locator('.printhead-material')).to_have_text('PLA')
            assert rig.remaining()[2] == 983.31
            assert not errors
        finally:
            browser.close()


def test_print_start_checks_remote_file_without_orca_export(rig):
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    result = rig.store.read()["last_preflight"]
    assert result["source"] == "print_start"
    assert result["filename"] == "single_tool.gcode"
    assert result["summary"] == "Print start: attention required"
    assert result["rows"][0]["status"] == "insufficient"
    assert rig.remaining() == [50.0, 1000.0, 1000.0, 1000.0]
    assert len(rig.store.read()["plans"]) == 1
    rig.control("complete")
    rig.poll()
    assert rig.remaining()[0] == 0.0
    rig.poll()
    assert rig.remaining()[0] == 0.0
    assert rig.store.read()["last_preflight"]["job_key"] == result["job_key"]


def test_verified_material_mismatch_is_advisory_not_printer_control(rig, monkeypatch):
    original = MoonrakerClient.inspect_gcode
    def inspect(client, filename):
        result = original(client, filename)
        client.last_inspection_metadata = {
            "slicer": "SnapmakerOrca", "filament_type": "PLA;PLA;PLA;PLA",
            "filament_weight": result[2],
        }
        return result
    monkeypatch.setattr(MoonrakerClient, "inspect_gcode", inspect)
    rig.store.update(lambda db: db["spools"]["spool0"].update({"material": "PETG"}))
    rig.store.update(lambda db: db["spools"].update({"spare": {"name": "Spare PLA", "material": "PLA", "remaining_g": 500.0}}))
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    check = rig.store.read()["last_preflight"]
    assert check["summary"] == "Print start: material advisory"
    assert check["material_checks"][0]["status"] == "mismatch"
    assert "does not pause" in check["reason"]
    assert "Spare PLA" in check["reason"]
    assert rig.store.read()["last_guard"]["state"] == "warning"
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"


def test_print_start_marks_unreadable_remote_metadata_unverified(rig, tmp_path):
    unknown = tmp_path / "unknown.gcode"
    unknown.write_text("G1 X1 Y1\n", encoding="utf-8")
    rig.control("select", path=str(unknown))
    rig.control("start")
    rig.poll()
    result = rig.store.read()["last_preflight"]
    assert result["summary"] == "Print start: unverified"
    assert result["rows"] == []
    assert "metadata was not found" in result["reason"]
    assert rig.remaining() == [1000.0] * 4


def test_remapped_tools_are_checked_and_charged_to_physical_spools(rig):
    plan_id = rig.plan("four_tool.gcode")
    with rig.simulator.lock:
        rig.simulator.data["extruder_map_table"] = [1, 1, 3, 0]
    rig.control("select", filename="four_tool.gcode")
    rig.control("start")
    rig.poll()
    db = rig.store.read()
    assert db["last_preflight"]["tool_mapping"] == [1, 1, 3, 0]
    assert [r["required_g"] for r in db["last_preflight"]["rows"]] == [40, 30, 0, 30]
    assert "T0 → T1" in db["last_preflight"]["reason"]
    run = next(iter(db["runs"].values()))
    assert run["physical_weights"] == [40, 30, 0, 30]
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [960, 970, 1000, 970]
    assert rig.store.read()["plans"][plan_id]["status"] == "committed"
    rig.poll()
    assert rig.remaining() == [960, 970, 1000, 970]


def test_missing_mapping_never_reports_ok_or_debits(rig):
    plan_id = rig.plan("single_tool.gcode")
    with rig.simulator.lock:
        rig.simulator.data["extruder_map_table"] = []
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    db = rig.store.read()
    assert db["last_preflight"]["summary"] == "Print start: unverified"
    assert db["last_preflight"]["rows"] == []
    assert db["plans"][plan_id]["status"] == "review"
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [1000] * 4


def test_strict_guard_treats_missing_mapping_as_unverified(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    with rig.simulator.lock:
        rig.simulator.data["extruder_map_table"] = []
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    assert rig.store.read()["last_preflight"]["summary"] == "Print start: unverified"


@pytest.mark.parametrize("auto_replenish", [True, None])
def test_automatic_or_unknown_replenishment_requires_accounting_review(rig, auto_replenish):
    plan_id = rig.plan("single_tool.gcode")
    with rig.simulator.lock:
        rig.simulator.data["auto_replenish_filament"] = auto_replenish
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    assert rig.store.read()["last_preflight"]["summary"] == "Print start: OK"
    assert rig.store.read()["plans"][plan_id]["status"] == "review"
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [1000] * 4


def test_replenishment_enabled_during_print_prevents_debit(rig):
    plan_id = rig.plan("single_tool.gcode")
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    assert rig.store.read()["plans"][plan_id]["status"] == "active"
    with rig.simulator.lock:
        rig.simulator.data["auto_replenish_filament"] = True
    rig.poll()
    assert rig.store.read()["plans"][plan_id]["status"] == "review"
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [1000] * 4


def test_changed_mapping_during_download_is_unverified_and_not_debited(rig):
    plan_id = rig.plan("single_tool.gcode")
    class ChangingClient(MoonrakerClient):
        def inspect_gcode(self, filename):
            result = super().inspect_gcode(filename)
            with rig.simulator.lock:
                rig.simulator.data["extruder_map_table"] = [1, 0, 2, 3]
            return result
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(client_factory=ChangingClient)
    db = rig.store.read()
    assert db["last_preflight"]["summary"] == "Print start: unverified"
    assert db["plans"][plan_id]["status"] == "review"
    rig.control("complete")
    rig.poll()
    assert rig.remaining() == [1000] * 4


def test_changed_mapping_before_pause_does_not_send_command(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    calls = {"mapping": 0, "pause": 0}
    class ChangingClient(MoonrakerClient):
        def mapping_snapshot(self, filename):
            calls["mapping"] += 1
            if calls["mapping"] == 3:
                with rig.simulator.lock:
                    rig.simulator.data["extruder_map_table"] = [1, 0, 2, 3]
            return super().mapping_snapshot(filename)
        def pause(self):
            calls["pause"] += 1
            return super().pause()
    runtime = GuardRuntime()
    rig.poll(runtime=runtime, client_factory=ChangingClient)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime, client_factory=ChangingClient)
    rig.wait_guard("pause_failed")
    assert calls["pause"] == 0
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"


def test_strict_guard_pauses_risky_new_job_once(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)  # Observe idle before arming printer control.
    assert runtime.armed
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "paused"
    result = rig.store.read()["last_guard"]
    assert result["state"] == "paused"
    assert result["filename"] == "single_tool.gcode"
    rig.poll(runtime=runtime)  # Same job cannot trigger another pause.
    assert rig.store.read()["last_guard"] == result
    assert rig.remaining()[0] == 50.0


def test_delayed_pause_does_not_block_monitor_or_send_twice(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    entered, release = threading.Event(), threading.Event()
    calls = []
    original_pause = rig.simulator.pause
    def delayed_pause():
        calls.append("pause")
        entered.set()
        assert release.wait(3)
        original_pause()
    rig.simulator.pause = delayed_pause
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    try:
        rig.poll(runtime=runtime)
        assert entered.wait(2)
        assert rig.store.read()["last_guard"]["state"] == "pause_requested"
        rig.poll(runtime=runtime)  # Monitoring continues while U1 processes PAUSE.
        assert calls == ["pause"]
    finally:
        release.set()
    rig.wait_guard("paused")
    assert calls == ["pause"]


def test_timed_out_pause_is_uncertain_and_disables_strict(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    entered, release, processed = threading.Event(), threading.Event(), threading.Event()
    calls = []
    original_pause = rig.simulator.pause
    def delayed_pause():
        calls.append("pause")
        entered.set()
        assert release.wait(3)
        original_pause()
        processed.set()
    rig.simulator.pause = delayed_pause
    def short_timeout(host, port):
        return MoonrakerClient(host, port, control_timeout=0.1)
    runtime = GuardRuntime()
    rig.poll(runtime=runtime, client_factory=short_timeout)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    try:
        rig.poll(runtime=runtime, client_factory=short_timeout)
        assert entered.wait(2)
        rig.wait_guard("pause_uncertain")
        assert rig.store.read()["printer"]["guard_mode"] == "warn"
        with pytest.raises(MoonrakerError, match="No Tracker-paused"):
            decide_guard(rig.store, "resume")
    finally:
        release.set()
    assert processed.wait(2)  # A timed-out request can still execute later.
    rig.poll(runtime=runtime)
    assert rig.store.read()["last_guard"]["state"] == "pause_uncertain"
    assert calls == ["pause"]


def test_timed_out_resume_cannot_be_sent_twice(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    calls = []
    class TimeoutClient(MoonrakerClient):
        def resume(self):
            calls.append("resume")
            raise MoonrakerError("timed out")
    with pytest.raises(MoonrakerError, match="outcome is unknown"):
        decide_guard(rig.store, "resume", client_factory=TimeoutClient)
    assert rig.store.read()["last_guard"]["state"] == "action_uncertain"
    assert rig.store.read()["printer"]["guard_mode"] == "warn"
    with pytest.raises(MoonrakerError, match="No Tracker-paused"):
        decide_guard(rig.store, "resume", client_factory=TimeoutClient)
    assert calls == ["resume"]


@pytest.mark.parametrize("pending,expected", [("pause_requested", "pause_uncertain"),
                                             ("resume_requested", "action_uncertain")])
def test_restart_marks_interrupted_control_uncertain_and_disables_strict(rig, pending, expected):
    def seed(db):
        db["printer"]["guard_mode"] = "strict"
        db["last_guard"] = {"job_key": "pending-job", "filename": "single_tool.gcode",
                            "state": pending, "summary": "Attention", "reason": "", "checked_at": 1}
    rig.store.update(seed)
    notified = threading.Event()
    monitor = PrinterMonitor(rig.store, interval=0.05, on_guard=lambda _: notified.set())
    monitor.start()
    try:
        rig.wait_guard(expected)
        assert notified.wait(2)
        assert rig.store.read()["printer"]["guard_mode"] == "warn"
        assert rig.simulator.status()["print_stats"]["state"] == "standby"
    finally:
        monitor.stop()


def test_guard_resume_and_cancel_require_matching_paused_job(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    assert decide_guard(rig.store, "resume") == "resume"
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"
    assert rig.store.read()["last_guard"]["state"] == "resumed"
    with pytest.raises(MoonrakerError, match="No Tracker-paused"):
        decide_guard(rig.store, "cancel")
    rig.control("complete")
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    assert decide_guard(rig.store, "cancel") == "cancel"
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "cancelled"
    assert rig.store.read()["last_guard"]["state"] == "cancelled"
    # The earlier resumed print completed; cancellation adds no second debit.
    assert rig.remaining()[0] == 0.0


def test_guard_refuses_action_after_paused_job_changes(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    rig.control("cancel")
    with pytest.raises(MoonrakerError, match="no longer paused"):
        decide_guard(rig.store, "resume")


def test_strict_guard_does_not_pause_job_active_before_monitor_armed(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    runtime = GuardRuntime()  # App launched after the print began.
    rig.poll(runtime=runtime)
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"
    assert rig.store.read()["last_guard"]["state"] == "warning"


def test_switching_printer_does_not_pause_a_preexisting_job(rig):
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    runtime = GuardRuntime()
    runtime.mode, runtime.target, runtime.armed = "strict", ("other-printer", 7125), True
    rig.poll(runtime=runtime)
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"
    assert rig.store.read()["last_guard"]["state"] == "warning"


def test_strict_guard_pauses_unverifiable_new_job(rig, tmp_path):
    unknown = tmp_path / "unknown.gcode"
    unknown.write_text("G1 X1 Y1\n", encoding="utf-8")
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "strict"}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", path=str(unknown))
    rig.control("start")
    rig.poll(runtime=runtime)
    rig.wait_guard("paused")
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "paused"
    assert rig.store.read()["last_preflight"]["summary"] == "Print start: unverified"
    assert rig.store.read()["last_guard"]["state"] == "paused"


def test_warn_and_off_modes_never_pause(rig):
    rig.store.update(lambda db: db["spools"]["spool0"].update({"remaining_g": 50.0}))
    runtime = GuardRuntime()
    rig.poll(runtime=runtime)
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"
    assert rig.store.read()["last_guard"]["state"] == "warning"
    rig.control("cancel")
    rig.store.update(lambda db: db["printer"].update({"guard_mode": "off"}))
    rig.control("select", filename="four_tool.gcode")
    rig.control("start")
    rig.poll(runtime=runtime)
    assert MoonrakerClient("127.0.0.1", rig.port).status()["state"] == "printing"
    assert rig.store.read()["last_guard"]["filename"] == "single_tool.gcode"


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


def test_four_tool_reassignment_before_start_requires_review(rig):
    plan_id = rig.plan("four_tool.gcode")

    def reassign(db):
        db["spools"]["replacement"] = {"name": "replacement", "material": "PLA", "remaining_g": 1000}
        db["slots"]["1"] = "replacement"

    rig.store.update(reassign)
    rig.control("select", filename="four_tool.gcode")
    rig.control("start")
    rig.poll()
    rig.control("complete")
    rig.poll()  # Reassignment makes the physical spool snapshot ambiguous.
    assert rig.remaining() == [1000, 1000, 1000, 1000]
    assert rig.store.read()["plans"][plan_id]["status"] == "review"
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


def test_monitoring_gap_before_completion_requires_review(rig):
    plan_id = rig.plan("single_tool.gcode")
    rig.control("select", filename="single_tool.gcode")
    rig.control("start")
    rig.poll()
    class Unavailable:
        def __init__(self, host, port): pass
        def status(self): raise MoonrakerError("connection lost")
    rig.poll(client_factory=Unavailable)  # Lost visibility makes automatic accounting unsafe.
    rig.control("complete")
    rig.poll(Store(rig.store.directory))
    assert rig.remaining() == [1000, 1000, 1000, 1000]
    assert rig.store.read()["plans"][plan_id]["status"] == "review"
    rig.poll(Store(rig.store.directory))
    assert rig.remaining() == [1000, 1000, 1000, 1000]
