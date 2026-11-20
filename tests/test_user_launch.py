import json
import re
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from tracker_app import data_directory, build_info, main
from tracker_uid_gui import serve
from tracker_uid_session import Session
from tracker_uid_sender import Sender


def test_user_data_separate_and_override(tmp_path, monkeypatch):
    monkeypatch.delenv('TRACKER20_DATA_DIR', raising=False)
    assert data_directory().name == 'Snapmaker Tracker 2.1'
    monkeypatch.setenv('TRACKER20_DATA_DIR', str(tmp_path))
    assert data_directory() == tmp_path
    assert build_info()['version'] == '2.1.0rc4-forecast-preview'
    assert main(['--data','ignored-lab-directory']) == 2
    assert not (tmp_path/'tracker.sqlite').exists()


@pytest.mark.parametrize('allowed', [None, ['http://127.0.0.1:19871']])
def test_catalog_cannot_bypass_allowlist(tmp_path, monkeypatch, allowed):
    session = Session(tmp_path, allowed_urls=[])
    settings = session.call('settings')
    session.call('save_settings', values={'spoolman_url':'http://127.0.0.1:19872'}, expected_revision=settings['revision'])
    requests = []
    monkeypatch.setattr('tracker_uid_spoolman.Client', lambda url: requests.append(url))
    sender = Sender(session, allowed) if allowed else None
    server = serve(session, session.fleet, sender=sender)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        with urlopen(url) as response: html = response.read().decode()
        token = json.loads(re.search(r'const TOKEN=("[^"]+")', html).group(1))
        with pytest.raises(HTTPError) as caught:
            urlopen(Request(url+'/api/refresh_catalog', data=b'{}', headers={'X-Tracker-Token':token,'Content-Type':'application/json'}))
        assert caught.value.code == 409
        assert 'не разрешён' in caught.value.read().decode()
        assert requests == []
        assert not session.connected
    finally:
        server.shutdown(); thread.join(); server.server_close(); session.close()


def test_sender_policy_tracks_explicit_settings_without_starting(tmp_path):
    session = Session(tmp_path)
    try:
        sender = Sender(session, lambda: [session.call('settings')['values'].get('spoolman_url','')])
        assert not sender.allowed_urls and sender._thread is None
        settings = session.call('settings')
        session.call('save_settings',values={'spoolman_url':'http://127.0.0.1:19872'},expected_revision=settings['revision'])
        assert sender.permits('http://127.0.0.1:19872/')
        assert not sender.permits('http://127.0.0.1:19873')
        assert not session.connected and sender._thread is None
    finally:
        session.close()
