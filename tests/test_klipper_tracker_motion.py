import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from dev.klipper_tracker_motion import TrackerMotion
from moonraker import MoonrakerClient, MoonrakerError


class Printer:
    def __init__(self):
        self.heads = [SimpleNamespace(last_position=100.0 * i) for i in range(4)]
        self.stats = SimpleNamespace(filename='test.gcode', state='standby', filament_used=0.0, info_current_layer=0)
        self.handlers = {}

    def register_event_handler(self, name, callback):
        self.handlers[name] = callback

    def lookup_object(self, name, *default):
        return {'extruder_list': self.heads, 'print_stats': self.stats}.get(name, default[0] if default else None)


def make_capture():
    printer = Printer()
    capture = TrackerMotion(SimpleNamespace(get_printer=lambda: printer))
    return printer, capture


def test_physical_heads_are_counted_separately_after_replenishment():
    printer, capture = make_capture()
    printer.handlers['print_stats:new_task_start']()
    printer.stats.state = 'printing'
    printer.heads[0].last_position += 80
    printer.heads[1].last_position += 20
    printer.stats.state = 'complete'
    printer.handlers['print_stats:stop']()
    result = capture.get_status(0)['capture']
    assert result['state'] == 'completed' and result['valid']
    assert result['head_mm'] == [80, 20, 0, 0]
    assert result['filename'] == 'test.gcode'
    assert result['initial_tag_uids'] is None
    assert result['final_tag_uids'] is None
    assert result['identity_verified'] is False


def test_tagged_and_untagged_spools_remain_distinct_and_port_event_is_recorded():
    printer, capture = make_capture()
    original_lookup = printer.lookup_object
    detector = SimpleNamespace(get_status=lambda _: {'info': [
        {'CARD_UID': [1, 2, 3, 4]}, {'CARD_UID': 0}, {'CARD_UID': 0}, {'CARD_UID': [8, 9, 10, 11]}]})
    printer.lookup_object = lambda name, *default: detector if name == 'filament_detect' else original_lookup(name, *default)
    printer.handlers['print_stats:new_task_start']()
    printer.handlers['filament_feed:port'](1, False)
    state = capture.get_status(0)['capture']
    assert state['initial_tag_uids'] == ['01020304', None, None, '08090a0b']
    assert state['spool_port_events'] == [False, True, False, False]
    assert state['identity_verified'] is False


@pytest.mark.parametrize('invalid_uid', [None, [1, 2, 3, 999], [], 'invalid', False])
def test_invalid_detector_data_is_not_interpreted_as_untagged(invalid_uid):
    printer, capture = make_capture()
    original_lookup = printer.lookup_object
    detector = SimpleNamespace(get_status=lambda _: {'info': [
        {'CARD_UID': [1, 2, 3, 4]}, {'CARD_UID': invalid_uid}, {'CARD_UID': 0}, {'CARD_UID': 0}]})
    printer.lookup_object = lambda name, *default: detector if name == 'filament_detect' else original_lookup(name, *default)
    printer.handlers['print_stats:new_task_start']()
    assert capture.get_status(0)['capture']['initial_tag_uids'] is None


def test_tag_snapshot_at_completion_and_invalid_event_fail_closed():
    printer, capture = make_capture()
    original_lookup = printer.lookup_object
    entries = [{'CARD_UID': [1, 2, 3, 4]}, {'CARD_UID': 0}, {'CARD_UID': 0}, {'CARD_UID': 0}]
    detector = SimpleNamespace(get_status=lambda _: {'info': entries})
    printer.lookup_object = lambda name, *default: detector if name == 'filament_detect' else original_lookup(name, *default)
    printer.handlers['print_stats:new_task_start']()
    entries[0] = {'CARD_UID': [4, 3, 2, 1]}
    printer.handlers['filament_feed:port'](0, 1)
    printer.stats.state = 'complete'
    printer.handlers['print_stats:stop']()
    result = capture.get_status(0)['capture']
    assert not result['valid']
    assert result['reason'] == 'Unrecognised spool port event'
    assert result['initial_tag_uids'][0] == '01020304'
    assert result['final_tag_uids'][0] == '04030201'


def test_recovery_cancel_and_invalid_counters_never_qualify():
    printer, capture = make_capture()
    printer.stats.filament_used = 10
    printer.handlers['print_stats:new_task_start']()
    assert not capture.get_status(0)['capture']['valid']
    printer.stats.state = 'cancelled'
    printer.handlers['print_stats:stop']()
    assert capture.get_status(0)['capture']['state'] == 'not_completed'
    printer.stats.filament_used = 0
    printer.heads[2].last_position = float('nan')
    printer.handlers['print_stats:new_task_start']()  # Monitoring errors never escape.
    assert capture.get_status(0)['capture'] is None


def test_moonraker_motion_evidence_validates_filename_and_lengths():
    printer, capture = make_capture()
    printer.handlers['print_stats:new_task_start']()
    class Opener:
        def open(self, url, timeout):
            data = {'print_stats': {'filename': printer.stats.filename}, 'tracker_motion': capture.get_status(0)}
            return BytesIO(json.dumps({'result': {'status': data}}).encode())
    client = MoonrakerClient('example.local', 7125, opener=Opener())
    assert client.motion_evidence()['head_mm'] == [0, 0, 0, 0]
    printer.stats.filename = 'another.gcode'
    with pytest.raises(MoonrakerError, match='identity'):
        client.motion_evidence()
