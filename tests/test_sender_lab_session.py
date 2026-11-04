import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import Timeout
from dev.labs.sender_lab_session import LabSession, default_directory


def saved(root, scenario='start_timeout'):
    with LabSession(root, scenario) as session:
        session.save_marker(34561, 34562)
        for name in ('inventory/spools_u1.json', 'sender/draft.json', 'sender/sender.sqlite'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        (root / 'report.json').write_text(json.dumps({'uploads':1,'start_requests':1,'accepted_starts':1}))


def test_default_directory_beside_bundle_not_user_preferences(monkeypatch):
    from dev.labs import sender_lab_session as module
    monkeypatch.setattr(module.sys,'frozen',True,raising=False)
    monkeypatch.setattr(module.sys,'executable','/tmp/test-build/TrackerSenderLab.app/Contents/MacOS/TrackerSenderLab')
    assert default_directory() == Path('/tmp/test-build/TrackerSenderLab.data').resolve()


def test_default_session_restores_without_scenario_or_resume(tmp_path):
    saved(tmp_path)
    before = {str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with LabSession(tmp_path) as session:
        assert session.resumed and session.scenario == 'start_timeout'
        assert session.ports == {'http_port':34561,'ws_port':34562}
        assert session.previous['start_requests'] == 1
    assert all(Path(p).read_bytes() == v for p,v in before.items())


def test_second_instance_cannot_reset_session(tmp_path):
    with LabSession(tmp_path):
        with pytest.raises(Timeout):
            with LabSession(tmp_path):
                pytest.fail('second instance entered')


@pytest.mark.parametrize('missing',['session.json','sender/draft.json','sender/sender.sqlite','inventory/spools_u1.json','report.json'])
def test_incomplete_state_fails_closed(tmp_path, missing):
    saved(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(ValueError,match='refusing'):
        with LabSession(tmp_path):
            pytest.fail('corrupt state accepted')


def test_scenario_change_does_not_reset_job(tmp_path):
    saved(tmp_path)
    with pytest.raises(ValueError,match='refusing to replace'):
        with LabSession(tmp_path, 'success'):
            pytest.fail('scenario changed')
    with LabSession(tmp_path) as session:
        assert session.scenario == 'start_timeout'


def test_main_no_arguments_reopens_same_blocked_job(tmp_path,monkeypatch):
    from dev.labs import sender_lab_session
    from dev.labs import sender_test_app
    import webview
    monkeypatch.setattr(sender_lab_session,'default_directory',lambda:tmp_path)
    captured = []
    def window(*args,**kwargs):
        captured.append(kwargs['js_api']._demo)
        return SimpleNamespace(load_url=lambda url:None)
    monkeypatch.setattr(webview,'create_window',window)
    first = True
    def gui(**kwargs):
        nonlocal first
        demo = captured[-1]
        c = demo.controller
        if first:
            import base64
            c.select({'filename':'test.gcode','content':base64.b64encode(demo.fixture.read_bytes()).decode()})
            request=c.draft['request']
            c.ledger.claim(request['request_id'], request['inventory_path'], request)
            c.ledger.set(request['request_id'],'outcome_unknown','lost response')
            c.draft['state']='outcome_unknown'
            c.draft['reason']='lost response'
            c._save()
            first = False
        else:
            assert c.status()['state']=='outcome_unknown'
            with pytest.raises(ValueError):
                c.action('start',{'confirmed':True})
            assert demo.mock.uploads == demo.mock.start_requests == []
    monkeypatch.setattr(webview,'start',gui)
    assert sender_test_app.main([])==0
    first_draft=(tmp_path/'sender/draft.json').read_bytes()
    assert sender_test_app.main([])==0
    assert (tmp_path/'sender/draft.json').read_bytes()==first_draft
    assert json.loads((tmp_path/'report.json').read_text())['resumed'] is True
