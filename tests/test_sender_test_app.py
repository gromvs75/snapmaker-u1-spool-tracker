import json
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_presend import request_data
from dev.sender_dashboard_demo import Demo
from presend import evaluate
from sender import strict_check


def test_frozen_checker_dispatch(monkeypatch, request_data):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(evaluate(request_data)).encode())
    monkeypatch.setattr(subprocess, 'run', run)
    strict_check(request_data, 3)
    assert calls[0][:3] == [sys.executable, '--presend-worker', '--request']


def test_worker_does_not_launch_gui(request_data, capsys):
    from pathlib import Path
    from sender_test_app import main
    path = Path(request_data['gcode_path']).parent / 'worker-request.json'
    path.write_text(json.dumps(request_data))
    assert main(['--presend-worker', '--request', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['decision'] == 'allow'


def test_demo_rejects_printer_and_settings_apis(tmp_path):
    with Demo(tmp_path) as demo:
        before = demo.store.path.read_bytes()
        for path, body in [('/api/printer/test', {}), ('/api/printer/config', {}),
                           ('/api/settings', {}), ('/api/printer/head-counters', None)]:
            request = Request(demo.url + path, data=json.dumps(body).encode() if body is not None else None,
                              headers={'Content-Type': 'application/json'})
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == 403
        assert demo.store.path.read_bytes() == before
        assert demo.mock.reads == demo.mock.uploads == demo.mock.start_requests == []
