import hashlib

import pytest

from dev.observer_fixture import payload
from slice_bed_marker import embedded_bed_identity
from slice_observer import SliceObserver
from tracker_uid_forecast import SliceForecast
from tracker_uid_session import Session


def marked(marker='; TRACKER_BED_V1 = 03'):
    return payload().replace(b'G1 X1', marker.encode() + b'\nG1 X1')


@pytest.mark.parametrize('number', [1, 2, 3, 15])
def test_slicer_zero_padded_number_is_not_file_rank(tmp_path, number):
    folder = tmp_path/'slices'/'project'/'Metadata'
    folder.mkdir(parents=True)
    p = folder/'.123.47.gcode'
    content = marked(f'; TRACKER_BED_V1 = {number:02}')
    p.write_bytes(content)
    # Old unlinked backup is irrelevant to a marker inside this exact slice.
    (folder/'model_settings.config').write_text('<config/>')
    session = Session(tmp_path/'db', allowed_urls=[])
    try:
        forecast = SliceForecast(session, tmp_path/'slices')
        forecast.poll(); forecast.observer.settle = 0
        entry = forecast.poll()['entries'][0]
        assert entry['plate'] == number
        assert entry['plate_identity'] == 'gcode_marker_v1'
        assert entry['sha256'] == hashlib.sha256(content).hexdigest()
        assert entry['mapping'] == 'unknown' and entry['weights'] == [10, 20, 0, 0]
        assert not session.connected and session.call('inspect')['debits'] == []
    finally:
        session.close()


@pytest.mark.parametrize('marker', [
    '; TRACKER_BED_V1 = 0', '; TRACKER_BED_V1 = -1',
    '; TRACKER_BED_V1 = {plate_number}', '; TRACKER_BED_V2 = 02',
    '; TRACKER_BED_V1 = 10000', '; TRACKER_BED_V1 = 2 junk',
    '; TRACKER_BED_V1 = 01\n; TRACKER_BED_V1 = 02',
    '; TRACKER_BED_V1 = 02\n; TRACKER_BED_V1 = 02',
])
def test_invalid_or_ambiguous_marker_is_not_guessed(marker):
    assert embedded_bed_identity(marked(marker)) == (None, 'invalid_marker')


def test_profile_template_in_config_is_not_a_sliced_number():
    content = payload().replace(b'; CONFIG_BLOCK_END',
        b'; machine_start_gcode = ; TRACKER_BED_V1 = {plate_number}\\nPRINT_START\n; CONFIG_BLOCK_END')
    assert embedded_bed_identity(content) == (None, 'absent')
    content = content.replace(b'G1 X1', b'; TRACKER_BED_V1 = 02\nG1 X1')
    assert embedded_bed_identity(content) == (2, 'gcode_marker_v1')


def test_reslice_reorder_restart_duplicates_and_incomplete_file(tmp_path):
    folder = tmp_path/'Metadata'; folder.mkdir()
    p = folder/'.123.99.gcode'; p.write_bytes(marked())
    observer = SliceObserver(tmp_path, settle_seconds=0)
    observer.poll(); assert observer.poll()[0]['plate'] == 3
    assert observer.poll() == []
    # Same model and same cache path; producer emits the new actual bed number.
    temp = p.with_suffix('.gcode.tmp'); temp.write_bytes(marked('; TRACKER_BED_V1 = 02'))
    assert observer.poll() == []
    assert observer.entries[str(p.relative_to(tmp_path))]['state'] == 'pending'
    temp.replace(p)
    observer.poll(); assert observer.poll()[0]['plate'] == 2
    observer = SliceObserver(tmp_path, settle_seconds=0)
    observer.poll(); assert observer.poll()[0]['plate'] == 2
    # Two copies of the same object on different beds retain different identities.
    q = folder/'.123.0.gcode'; q.write_bytes(marked('; TRACKER_BED_V1 = 01'))
    observer.poll(); assert observer.poll()[0]['plate'] == 1
    assert sorted(e['plate'] for e in observer.entries.values()) == [1, 2]


def test_invalid_marker_does_not_fall_back_to_project_metadata(tmp_path):
    folder = tmp_path/'slices'/'project'/'Metadata'; folder.mkdir(parents=True)
    p = folder/'.123.47.gcode'; p.write_bytes(marked('; TRACKER_BED_V1 = {plate_number}'))
    (folder/'model_settings.config').write_text('<config><plate>'
        '<metadata key="plater_id" value="1"/>'
        '<metadata key="gcode_file" value="Metadata/.123.47.gcode"/>'
        '</plate></config>')
    session = Session(tmp_path/'db', allowed_urls=[])
    try:
        forecast = SliceForecast(session, tmp_path/'slices')
        forecast.poll(); forecast.observer.settle = 0
        entry = forecast.poll()['entries'][0]
        assert entry['state'] == 'ready' and entry['plate'] is None
        assert entry['plate_identity'] == 'invalid_marker'
    finally:
        session.close()
