import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip('websockets', reason='Install requirements/sender.txt for network sender tests')

from test_presend import request_data
from dev.mock_sender_u1 import MockSenderU1
from sender import Ledger, LocalTransport, SendError, send


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / 'sender.sqlite')


@pytest.mark.parametrize('action', ['send', 'print'])
def test_real_http_ws_happy_path(request_data, ledger, action):
    request_data['action'] = action
    before = Path(request_data['inventory_path']).read_bytes()
    with MockSenderU1() as server:
        result = send(request_data, LocalTransport(server.http_url, server.ws_url), ledger)
        assert result['state'] == ('active' if action == 'print' else 'sent'), result
        assert len(server.uploads) == 1
        assert server.uploads[0]['print'] == 'false'
        assert len(server.accepted_starts) == (1 if action == 'print' else 0)
        assert next(iter(server.files.values())) == Path(request_data['gcode_path']).read_bytes()
        if action == 'print':
            assert json.loads(server.accepted_starts[0]['options']['MAP_TABLE']) == [[0,0],[1,1],[2,2],[3,3]]
        # New Ledger object represents a restarted sender; no network retry.
        send(request_data, LocalTransport(server.http_url, server.ws_url), Ledger(ledger.path))
        assert len(server.uploads) == 1
        assert len(server.accepted_starts) == (1 if action == 'print' else 0)
    assert Path(request_data['inventory_path']).read_bytes() == before


@pytest.mark.parametrize('fault', ['deny', 'checker_crash', 'checker_timeout', 'checker_bad_json'])
@pytest.mark.parametrize('action', ['send', 'print'])
def test_preflight_failure_has_zero_writes(request_data, ledger, tmp_path, fault, action):
    request_data['action'] = action
    command = None
    if fault == 'deny':
        path = Path(request_data['inventory_path'])
        data = json.loads(path.read_text())
        data['spools']['s1']['remaining_g'] = 0
        path.write_text(json.dumps(data))
    else:
        checker = tmp_path / 'fault.py'
        checker.write_text({'checker_crash': 'raise RuntimeError("fault")',
                            'checker_timeout': 'import time; time.sleep(5)',
                            'checker_bad_json': 'print("invalid")'}[fault])
        command = [sys.executable, str(checker)]
    with MockSenderU1() as server:
        result = send(request_data, LocalTransport(server.http_url, server.ws_url), ledger,
                      checker_timeout=.1, checker_command=command)
        assert result['state'] == 'blocked', result
        assert server.uploads == server.start_requests == server.reads == []


@pytest.mark.parametrize('fault,state', [
    ('busy','blocked'), ('auto_replenish','blocked'),
    ('upload_reject','upload_unknown'), ('upload_timeout','upload_unknown'),
    ('redirect','upload_unknown'), ('corrupt','uploaded_blocked'), ('queued','upload_unknown'),
    ('nested_error','outcome_unknown'), ('rpc_error','outcome_unknown'),
    ('start_timeout','outcome_unknown'), ('start_disconnect','outcome_unknown'),
    ('wrong_mapping','outcome_unknown'), ('invalid_mapping','outcome_unknown'),
])
def test_network_faults_never_retry_start(request_data, ledger, fault, state):
    request_data['action'] = 'print'
    with MockSenderU1(fault) as server:
        transport = LocalTransport(server.http_url, server.ws_url, timeout=.15)
        result = send(request_data, transport, ledger)
        assert result['state'] == state, result
        starts = len(server.start_requests)
        uploads = len(server.uploads)
        assert starts == (1 if state == 'outcome_unknown' else 0)
        if fault in ('start_timeout', 'start_disconnect'):
            assert len(server.accepted_starts) == 1  # Request WAS accepted; response lost.
        restarted = Ledger(ledger.path)
        assert restarted.get(request_data['request_id'])['state'] == state
        send(request_data, transport, restarted)
        # Even a new request cannot bypass an unresolved reservation.
        if state != 'blocked':
            other = dict(request_data, request_id='new-request')
            send(other, transport, restarted)
        assert len(server.start_requests) == starts
        assert len(server.uploads) == uploads


@pytest.mark.parametrize('changed', ['inventory', 'file'])
def test_change_after_upload_prevents_start(request_data, ledger, changed):
    request_data['action'] = 'print'
    with MockSenderU1() as server:
        def mutate():
            path = Path(request_data['inventory_path' if changed == 'inventory' else 'gcode_path'])
            path.write_bytes(path.read_bytes() + b'\n')
        server.after_upload = mutate
        result = send(request_data, LocalTransport(server.http_url, server.ws_url), ledger)
        assert result['state'] == 'uploaded_blocked'
        assert len(server.uploads) == 1
        assert server.start_requests == []


def test_concurrent_requests_claim_inventory_once(request_data, ledger):
    request_data['action'] = 'print'
    with MockSenderU1() as server:
        def attempt(index):
            return send(dict(request_data, request_id='job-' + str(index)),
                        LocalTransport(server.http_url, server.ws_url), Ledger(ledger.path))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [1,2]))
        assert sorted(r['state'] for r in results) == ['active', 'blocked']
        assert len(server.uploads) == len(server.start_requests) == 1


def test_crash_marker_blocks_new_attempt(request_data, ledger):
    ledger.claim('previous', str(Path(request_data['inventory_path']).resolve()), {})
    ledger.set('previous', 'start_requested')  # Durable state left by killed process.
    with MockSenderU1() as server:
        result = send(request_data, LocalTransport(server.http_url, server.ws_url), Ledger(ledger.path))
        assert result['state'] == 'blocked'
        assert server.uploads == server.start_requests == []


@pytest.mark.parametrize('url', ['http://192.168.2.133:7125', 'http://localhost:7125',
                                  'http://127.0.0.1:7125@evil.example:80', 'https://127.0.0.1:7125'])
def test_non_test_destinations_refused(url):
    with pytest.raises(SendError):
        LocalTransport(url, 'ws://127.0.0.1:9876/websocket')


def test_cli_in_separate_process(request_data, tmp_path):
    request_data['action'] = 'print'
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request_data))
    with MockSenderU1() as server:
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'src' / 'sender.py'),
                   '--request', str(path), '--ledger', str(tmp_path / 'cli.sqlite'),
                   '--http', server.http_url, '--ws', server.ws_url]
        first = subprocess.run(command, capture_output=True, timeout=5)
        second = subprocess.run(command, capture_output=True, timeout=5)
        assert first.returncode == 0, first.stderr + first.stdout
        assert second.returncode == 23
        assert len(server.accepted_starts) == 1


def test_killed_sender_does_not_repeat_accepted_start(request_data, tmp_path):
    request_data['action'] = 'print'
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request_data))
    ledger_path = tmp_path / 'crash.sqlite'
    with MockSenderU1('start_timeout') as server:
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'src' / 'sender.py'),
                   '--request', str(path), '--ledger', str(ledger_path),
                   '--http', server.http_url, '--ws', server.ws_url]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert server.start_event.wait(3)
            process.kill()
            process.communicate(timeout=3)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)
        assert Ledger(ledger_path).get(request_data['request_id'])['state'] == 'start_requested'
        retry = subprocess.run(command, capture_output=True, timeout=3)
        assert retry.returncode == 23
        assert len(server.accepted_starts) == 1
        assert len(server.uploads) == 1


def test_mapping_changed_after_upload_blocks_start(request_data, ledger):
    request_data['action'] = 'print'
    with MockSenderU1() as server:
        server.after_upload = lambda: request_data['mapping'].__setitem__(0, 1)
        result = send(request_data, LocalTransport(server.http_url, server.ws_url), ledger)
        assert result['state'] == 'uploaded_blocked'
        assert len(server.uploads) == 1
        assert not server.start_requests


def test_sender_os_sandbox():
    import os
    import socket
    import tempfile
    if os.environ.get('TRACKER_ASSERT_SENDER_SANDBOX') != '1':
        pytest.skip('Run with documented loopback-only OS sandbox')
    # Documentation-only TEST-NET destination; the OS must refuse immediately.
    with socket.socket() as sock:
        sock.settimeout(.1)
        with pytest.raises(PermissionError):
            sock.connect(('192.0.2.1', 9))
    with pytest.raises(PermissionError):
        with tempfile.NamedTemporaryFile(dir=Path(__file__).resolve().parents[1]):
            pass
