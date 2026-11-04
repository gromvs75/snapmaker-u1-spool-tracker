import os
from pathlib import Path

import pytest

import slice_observer as module
from slice_observer import SliceObserver, ForecastAttention
from dev.observer_fixture import payload
from dev.labs.observer_lab_app import forecast_text


@pytest.fixture
def lab(tmp_path):
    folder = tmp_path / 'date' / 'model#42#1' / 'Metadata'
    folder.mkdir(parents=True)
    clock = [0.0]
    watcher = SliceObserver(tmp_path, clock=lambda: clock[0])
    def poll():
        clock[0] += 2
        return watcher.poll()
    return folder, watcher, poll


def test_partial_stable_file_never_accepted(lab):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    p.write_bytes(payload()[:-30])
    for _ in range(5):
        assert poll() == []
    assert next(iter(watcher.entries.values()))['state'] == 'pending'
    p.write_bytes(payload())
    assert poll() == []
    assert len(poll()) == 1
    assert poll() == []


def test_tmp_even_complete_is_not_committed(lab):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    temp = Path(str(p) + '.tmp')
    temp.write_bytes(payload())
    for _ in range(5):
        assert poll() == []
    temp.replace(p)
    assert poll() == []
    assert len(poll()) == 1


def test_reslice_invalidates_old_forecast_then_notifies_once(lab):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    p.write_bytes(payload())
    poll()
    first = poll()[0]
    temp = Path(str(p) + '.tmp')
    temp.write_bytes(payload('120, 0, 0, 0')[:-20])
    assert poll() == []
    assert next(iter(watcher.entries.values()))['state'] == 'pending'
    assert 'weights' not in next(iter(watcher.entries.values()))
    temp.write_bytes(payload('120, 0, 0, 0'))
    temp.replace(p)
    poll()
    second = poll()[0]
    assert second['sha256'] != first['sha256']
    assert second['weights'][0] == 120
    assert poll() == []
    assert 'НЕ ХВАТИТ' in forecast_text(second)


def test_identical_rewrite_no_spam(lab):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    p.write_bytes(payload())
    poll()
    assert len(poll()) == 1
    p.write_bytes(payload())
    assert poll() == []
    assert poll() == []
    assert next(iter(watcher.entries.values()))['state'] == 'ready'


def test_multiple_plates_and_models_distinct_same_content(lab):
    folder, watcher, poll = lab
    other = folder.parents[1] / 'model#42#2' / 'Metadata'
    other.mkdir(parents=True)
    for path in [folder / '.42.1.gcode', folder / '.42.2.gcode', other / '.42.1.gcode']:
        path.write_bytes(payload())
    poll()
    events = poll()
    assert len(events) == 3
    assert len({e['source'] for e in events}) == 3
    assert all(e['mapping'] == 'unknown' for e in events)
    calls = []
    attention = ForecastAttention(calls.append)
    attention.accept(events)
    attention.accept(poll())
    assert len(calls) == attention.batches == 1
    assert len(calls[0]) == 3


@pytest.mark.parametrize('bad', [
    payload().replace(b'10, 20, 0, 0', b'nan, 0, 0, 0'),
    payload().replace(b'10, 20, 0, 0', b'-1, 0, 0, 0'),
    payload().replace(b'; CONFIG_BLOCK_END', b'; CONFIG_BLOCK_END\nG1 X20'),
    payload().replace(b'; filament used', b'; unknown'),
    payload().replace(b'; CONFIG_BLOCK_START', b'; filament used [g] = 1\n; CONFIG_BLOCK_START'),
    payload().replace(b'; EXECUTABLE_BLOCK_END', b''),
    payload().rstrip(), b'\xff', b'',
])
def test_invalid_format_fails_without_popup(lab, bad):
    folder, watcher, poll = lab
    (folder / '.42.1.gcode').write_bytes(bad)
    assert poll() == poll() == poll() == []


def test_change_during_snapshot_rejected(lab, monkeypatch):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    p.write_bytes(payload())
    original = Path.lstat
    def racing(path):
        if path == p:
            p.write_bytes(payload('99, 0, 0, 0'))
        return original(path)
    monkeypatch.setattr(Path, 'lstat', racing)
    assert poll() == []
    assert next(iter(watcher.entries.values()))['state'] == 'pending'


def test_deleted_file_withdraws_preview(lab):
    folder, watcher, poll = lab
    p = folder / '.42.1.gcode'
    p.write_bytes(payload())
    poll()
    poll()
    p.unlink()
    assert poll() == []
    assert next(iter(watcher.entries.values()))['state'] == 'removed'


def test_symlinks_and_unrelated_files_ignored(lab, tmp_path):
    folder, watcher, poll = lab
    real = tmp_path / 'unrelated.gcode'
    real.write_bytes(payload())
    (folder / '.42.1.gcode').symlink_to(real)
    (folder / 'human.gcode').write_bytes(payload())
    (folder.parent / 'link').symlink_to(folder, target_is_directory=True)
    assert poll() == poll() == []
    assert len(watcher.entries) == 1


def test_size_limit(lab, monkeypatch):
    folder, watcher, poll = lab
    (folder / '.42.1.gcode').write_bytes(payload())
    monkeypatch.setattr(module, 'MAX_BYTES', 10)
    assert poll() == poll() == []


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='POSIX FIFO is unavailable on Windows')
def test_fifo_does_not_block(lab):
    folder, watcher, poll = lab
    os.mkfifo(folder / '.42.1.gcode')
    assert poll() == []


def test_pending_preview_has_no_stock_claim():
    text = forecast_text({'state': 'pending'})
    assert 'Прогноз недоступен' in text
    assert 'хватит' not in text


def test_cli_layout_explicit_and_separate(tmp_path):
    clock = [0.0]
    cli = SliceObserver(tmp_path, layout='cli', clock=lambda: clock[0])
    ordinary = SliceObserver(tmp_path, clock=lambda: clock[0])
    p = tmp_path / 'plate_1.gcode'
    temp = tmp_path / 'plate_1.gcode.tmp'
    temp.write_bytes(payload())
    assert cli.poll() == []
    temp.replace(p)
    (tmp_path / 'plate_2.gcode').write_bytes(payload('3, 0, 0, 0'))
    (tmp_path / 'unrelated.gcode').write_bytes(payload())
    assert cli.poll() == ordinary.poll() == []
    clock[0] = 2
    events = cli.poll()
    assert {e['source'] for e in events} == {'plate_1.gcode', 'plate_2.gcode'}
    assert ordinary.poll() == []


def test_unknown_layout_rejected(tmp_path):
    with pytest.raises(ValueError):
        SliceObserver(tmp_path, layout='automatic')


def test_special_file_rejected_before_open(monkeypatch):
    import stat
    from types import SimpleNamespace
    from gcode import GCodeError
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFIFO))
    monkeypatch.setattr(module.os, 'open', lambda *args: pytest.fail('Special file must never be opened'))
    with pytest.raises(GCodeError, match='Unsupported file type'):
        module.read_snapshot(path)
