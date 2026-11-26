from base64 import b64encode
from contextlib import contextmanager
from hashlib import sha256

from dev.observer_fixture import payload
from tracker_desktop_model import forecast_view
from tracker_macos_orca import MacOrcaDialog
from tracker_orca_preprint import OrcaPreprint, match_selection, preprint_address
from tracker_uid_forecast import SliceForecast
from tracker_uid_session import Session
from tracker_user_tray import tray_model


URL = 'http://127.0.0.1:30996/web/flutter_web/prepare_print?mode=1&id=c5acae72-6ffc-11ef-868d-2c594eb4a957'


def controls(second='2', printer='U1'):
    return [
        ('AXStaticText', ('Model Information',)),
        ('AXPopUpButton', ('Select Printer ' + printer,)),
        ('AXStaticText', ('Configure Filaments',)),
        ('AXButton', ('PLA 21.68g 1',)),
        ('AXButton', ('PLA 21.44g ' + second,)),
        ('AXStaticText', ('Print Preferences',)),
        ('AXButton', ('Start Print',)),
    ]


def context(path, content):
    return {
        'file_path': str(path),
        'active_file': {'file_path': str(path), 'checksum': b64encode(sha256(content).digest()).decode()},
        'filament_mapping': {'filament_weight': [21.684901779, 21.443052848, 0, 0]},
    }


def test_live_mix_remap_updates_cards_and_tray_without_changing_balances(tmp_path, monkeypatch):
    session = Session(tmp_path / 'profile', allowed_urls=[])
    try:
        settings = session.call('settings')
        session.call('save_settings', values={
            'printers': [dict(id='u1', name='U1', url='http://127.0.0.1:19811'),
                         dict(id='other', name='Other', url='http://127.0.0.1:19812')],
            'selected_printer': 'u1', 'safety_margin_g': '5',
        }, expected_revision=settings['revision'])
        original_snapshot = session.fleet.snapshot

        def printer_snapshot():
            fleet = original_snapshot()
            fleet['u1'].update(state='module_missing', printer_connected=True, print_state='standby')
            return fleet

        monkeypatch.setattr(session.fleet, 'snapshot', printer_snapshot)
        for channel, grams in [('0', 390.771), ('1', 177.608), ('3', 817.59)]:
            session.call(
                'create_spool', 'Spool ' + channel, grams,
                details={'material': 'PLA', 'color': '#ff8811'},
                assignment=dict(printer_id='u1', channel=channel, expected_version='', confirmed=True),
            )

        root = tmp_path / 'slices'
        path = root / 'mixed' / 'Metadata' / '.41.0.gcode'
        path.parent.mkdir(parents=True)
        # Orca emits base F1/F2 weights for virtual mix #5.
        content = payload('21.68, 21.44, 0, 0').replace(
            b'; printer_model', b'; filament_colour = #151a1c;#ffffff;#ff8811;#2b9c70\n'
                                b'; filament_type = PLA;PLA;PLA;PLA\n; printer_model',
        )
        path.write_bytes(content)
        dialog = (URL, controls())
        calls = []

        def read_context(address):
            calls.append(address)
            return context(path, content)

        def read_dialog():
            return dialog

        read_dialog.permission_required = False
        forecast = SliceForecast(session, root, orca=OrcaPreprint(read_dialog, read_context))
        forecast.poll()
        forecast.observer.settle = 0
        initial = forecast.poll()
        first_orca = tray_model(initial)['orca_event']
        assert first_orca[1] == ((1, '0'), (2, '1'))
        displayed = forecast_view(initial, 'u1')
        first_revision = displayed['slice_revision']
        first = displayed['entries'][0]
        assert first['mapping_source'] == 'orca'
        assert [row['tool'] for row in first['rows']] == ['T0', 'T1']

        dialog = (URL, controls('4'))
        snapshot = forecast.poll()
        displayed = forecast_view(snapshot, 'u1')
        current = displayed['entries'][0]
        assert displayed['orca_source'] == first['source']
        assert displayed['slice_revision'] == first_revision
        assert current['status'] == 'ok'
        assert [(r['tool'], r['used'], round(r['after'], 2)) for r in current['rows']] == [
            ('T0', 21.68, 369.09), ('T3', 21.44, 796.15),
        ]
        model = tray_model(snapshot)
        assert model['orca_event'] == (first_orca[0], ((1, '0'), (2, '3')))
        assert model['event'] == tray_model(initial)['event']
        assert model['mapping'] == 'По назначениям Orca'
        assert 'Нужно 21,44 г' in tray_model(snapshot)['heads'][3]['title']
        assert forecast_view(snapshot, 'other')['entries'][0].get('mapping_source') is None
        assert calls == [preprint_address(URL)]

        dialog = (URL, controls('3'))
        unassigned = forecast_view(forecast.poll(), 'u1')['entries'][0]
        assert unassigned['status'] == 'unknown'
        assert unassigned['rows'][1]['tool'] == 'T2' and unassigned['rows'][1]['spool_id'] is None

        dialog = (URL, controls('1'))
        combined = forecast_view(forecast.poll(), 'u1')['entries'][0]['rows']
        assert [(row['tool'], round(row['used'], 2)) for row in combined] == [('T0', 43.12)]

        dialog = (URL, controls('9'))
        current = forecast_view(forecast.poll(), 'u1')['entries'][0]
        assert current['mapping_source'] == 'orca_pending' and not current['rows']

        dialog = None
        read_dialog.permission_required = True
        closed = forecast.poll()
        assert tray_model(closed)['orca_permission_required']
        assert forecast_view(closed, 'u1')['orca_permission_required']
        current = forecast_view(closed, 'u1')['entries'][0]
        assert 'mapping_source' not in current
        assert tray_model(closed)['orca_event'] is None

        dialog = (URL, controls('4'))
        read_dialog.permission_required = False
        reopened = tray_model(forecast.poll())['orca_event']
        assert reopened[0] != first_orca[0] and reopened[1] == model['orca_event'][1]
        assert session.call('inspect')['debits'] == []
        assert session.call('inspect')['jobs'] == []
    finally:
        session.close()


def test_context_cannot_bind_wrong_file_or_printer(tmp_path):
    path = tmp_path / 'project' / 'Metadata' / '.41.0.gcode'
    path.parent.mkdir(parents=True)
    data = b'gcode'
    path.write_bytes(data)
    info = context(path, data)
    entries = [dict(source=str(path.relative_to(tmp_path)), state='ready',
                    sha256=sha256(data).hexdigest(), weights=[21.68, 21.44, 0, 0])]
    printers = {'a': {'name': 'My Tracker alias', 'configured_name': 'U1'}}
    assert match_selection(info, controls('4'), tmp_path, entries, printers).channels == {1: '0', 2: '3'}
    swapped_weights = controls('4')
    swapped_weights[3:5] = reversed(swapped_weights[3:5])
    assert match_selection(info, swapped_weights, tmp_path, entries, printers).channels is None
    assert match_selection(info, controls(printer='Other'), tmp_path, entries, printers) is None
    assert match_selection(info, controls(), tmp_path, entries, dict(printers, b={'name': 'U1'})) is None
    assert match_selection(info, controls(), path.parent, entries, printers) is None
    entries[0]['sha256'] = 'b' * 64
    assert match_selection(info, controls(), tmp_path, entries, printers) is None
    assert preprint_address(URL.replace('127.0.0.1', 'example.com')) is None
    assert preprint_address(URL.replace('prepare_print', 'device')) is None
    assert preprint_address(URL + '&id=duplicate') is None


def test_ax_reader_only_activates_flutter_semantics():
    class StubAccessibility:
        attrs = {
            2: {'AXSubrole': 'AXDialog', 'AXRole': 'AXWindow'},
            3: {'AXRole': 'AXWebArea', 'AXURL': URL},
            4: {'AXRole': 'AXButton', 'AXDescription': 'Enable accessibility'},
            6: {'AXRole': 'AXButton', 'AXDescription': 'Start Print'},
        }
        pressed = []
        expanded = False

        def application(self, pid):
            return 1

        def timeout(self, app, seconds):
            pass

        def release(self, app):
            pass

        def text(self, element, attr):
            if element >= 10:
                role, labels = controls('4')[element - 10]
                return {'AXRole': role, 'AXDescription': labels[0]}.get(attr, '')
            return self.attrs.get(element, {}).get(attr, '')

        @contextmanager
        def children(self, element, name='AXChildren'):
            children = {1: [2], 2: [3], 3: list(range(10, 17)) if self.expanded else [4, 6]}
            yield children.get(element, [])

        def press(self, element):
            self.pressed.append(element)
            self.expanded = True

    ax = StubAccessibility()
    reader = MacOrcaDialog(ax)
    assert reader.read_windows(1) == (URL, [('AXButton', ('Start Print',))])
    assert reader.read_windows(1) == (URL, controls('4'))
    assert ax.pressed == [4]
