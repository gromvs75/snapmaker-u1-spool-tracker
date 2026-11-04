import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from backup import create_backup
from dev.sender_dashboard_demo import Demo
from sender_test_backup import LabBackupBridge


def bridge_for(demo, selected):
    bridge = LabBackupBridge(demo, SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1, SAVE=2)))
    bridge.window = SimpleNamespace(create_file_dialog=lambda *a, **kw: [str(selected)] if selected else None)
    return bridge


def test_lab_import_invalidates_check_and_disarms_monitor(tmp_path):
    with Demo(tmp_path) as demo:
        backup = create_backup(demo.store, 'test')
        backup['data']['spools']['s0']['remaining_g'] = 77
        backup['data']['printer']['enabled'] = True
        backup['data']['printer']['host'] = '192.0.2.1'
        source = tmp_path / 'backup.json'
        source.write_text(json.dumps(backup))
        demo.controller.select({'filename':'test.gcode','content':base64.b64encode(demo.fixture.read_bytes()).decode()})
        demo.controller.draft['state'] = 'checked'
        before = demo.store.path.read_bytes()
        result = bridge_for(demo, source).import_backup()
        assert result['status'] == 'ok'
        assert json.loads(Path(result['safety_backup']).read_bytes()) == json.loads(before)
        restored = demo.store.read()
        assert restored['spools']['s0']['remaining_g'] == 77
        assert restored['printer']['enabled'] is False
        assert demo.controller.draft['state'] == 'selected'
        assert demo.controller.draft['rows'] == []
        assert demo.mock.reads == demo.mock.uploads == demo.mock.start_requests == []


@pytest.mark.parametrize('state', ['sent','upload_unknown','outcome_unknown','active','start_requested'])
def test_import_cannot_reset_unresolved_job(tmp_path,state):
    with Demo(tmp_path) as demo:
        demo.controller.draft['state'] = state
        before = demo.store.path.read_bytes()
        bridge = bridge_for(demo, None)
        bridge.window.create_file_dialog = lambda *a, **kw: pytest.fail('dialog must not open')
        with pytest.raises(ValueError, match='Импорт заблокирован'):
            bridge.import_backup()
        assert demo.store.path.read_bytes() == before
        assert demo.controller.draft['state'] == state


def test_import_rechecks_state_after_dialog(tmp_path):
    with Demo(tmp_path) as demo:
        source = tmp_path / 'backup.json'
        source.write_text(json.dumps(create_backup(demo.store,'test')))
        before = demo.store.path.read_bytes()
        bridge = bridge_for(demo, source)
        def dialog(*a, **kw):
            demo.controller.busy = True
            return str(source)
        bridge.window.create_file_dialog = dialog
        with pytest.raises(ValueError, match='Импорт заблокирован'):
            bridge.import_backup()
        assert demo.store.path.read_bytes() == before


def test_cancel_and_bad_import_preserve_inventory(tmp_path):
    with Demo(tmp_path) as demo:
        before = demo.store.path.read_bytes()
        assert bridge_for(demo,None).import_backup() == {'status':'cancelled'}
        source = tmp_path / 'bad.json'
        source.write_text('{}')
        with pytest.raises(Exception, match='not a Snapmaker'):
            bridge_for(demo,source).import_backup()
        assert demo.store.path.read_bytes() == before
