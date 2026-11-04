import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from backup import create_backup
from storage import Store, StorageError
from forecast_backup import ForecastBackupBridge
from dev.labs.forecast_lab_app import ForecastState


def test_restore_four_spools_and_forecast(tmp_path):
    store = Store(tmp_path/'inventory', legacy_paths=())
    old = store.read()
    doc = create_backup(store, '1.2-alpha')
    doc['data']['spools'] = {f'b{i}': {'name': f'Restored {i}', 'material': 'PLA', 'remaining_g': n}
                            for i,n in enumerate([77.5, 123.25, 8, 400])}
    doc['data']['slots'] = {str(i+1): f'b{i}' for i in range(4)}
    doc['data']['printer']['enabled'] = True
    path = tmp_path/'restore.json';path.write_text(json.dumps(doc))
    bridge = ForecastBackupBridge(store, SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1)), tmp_path)
    bridge.window = SimpleNamespace(create_file_dialog=lambda *a, **kw: [str(path)])
    result = bridge.import_backup()
    restored = store.read()
    assert restored['spools'] == doc['data']['spools']
    assert restored['slots'] == doc['data']['slots']
    assert not restored['printer']['enabled']
    assert json.loads(Path(result['safety_backup']).read_text()) == old
    state = ForecastState(store=store)
    state.accept([{'source': '.1.0.gcode', 'weights': [3.28,0,0,0]}])
    assert state.snapshot()['entries'][0]['rows'][0]['after'] == 74.22
    before = store.path.read_bytes()
    path.write_text('{}')
    with pytest.raises(StorageError): bridge.import_backup()
    assert store.path.read_bytes() == before
    bridge.window.create_file_dialog = lambda *a, **kw: None
    assert bridge.import_backup()['status'] == 'cancelled'
    assert store.path.read_bytes() == before
