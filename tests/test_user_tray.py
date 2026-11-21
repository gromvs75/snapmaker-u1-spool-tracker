from dev.observer_fixture import payload
from slice_observer import SliceObserver
from tracker_user_tray import tray_model,create_tray_icon,create_toolhead_menu_icon,create_material_menu_icon
from tracker_uid_forecast import enrich
from test_uid_forecast import entry,heads


def test_tray_uses_latest_plate_and_selected_printer_balances():
    e = entry([15.08, 2.36, 0, 0], plate=2, colors=['#FD8008', '#000000'])
    snapshot = enrich(dict(entries=[e], latest=e['source']), dict(
        printers={'a': dict(heads=heads(99000)), 'b': dict(name='Мастерская B', heads=heads(30001))},
        selected_printer='b', safety_margin_g=5, accounted={},
    ))
    model = tray_model(snapshot)
    assert '17,44 г' in model['forecast'] and 'Стол 2' in model['forecast']
    assert model['materials'][0]['color'] == '#FD8008' and model['materials'][0]['grams'] == 15.08
    assert model['status'] == 'unknown' and all('после' not in head['title'] for head in model['heads'])
    assert '30,0 г' in model['heads'][0]['title'] and model['title'] == 'Мастерская B (4 головки)'


def test_tray_shows_deficit_on_color_matched_head():
    e = entry([15.08, 2.36], plate=1, colors=['#FD8008','#000000'], filament_types=['PLA','PLA'])
    h = heads(430700)
    h[0]['spool']['details'] = dict(color='#151a1c', material='PLA')
    h[2]['spool'].update(remaining_mg=15000, details=dict(color='#ff7f26', material='PLA +'))
    snapshot = enrich(dict(entries=[e], latest=e['source']), dict(
        printers={'u1': dict(heads=h)}, selected_printer='u1', safety_margin_g=5, accounted={},
    ))
    model = tray_model(snapshot)
    assert model['status'] == 'shortage'
    assert 'После ≈ 428,34 г' in model['heads'][0]['title']
    assert 'Не хватает с резервом 5,08 г' in model['heads'][2]['title']
    assert 'Нужно' not in model['heads'][1]['title']


def test_white_rgba_slice_shows_forecast_on_t1_before_print(tmp_path):
    folder = tmp_path / 'project' / 'Metadata'
    folder.mkdir(parents=True)
    (folder / '.42.7.gcode').write_bytes(payload('0.00, 4.27, 0.00, 0.00').replace(
        b'; printer_model', b'; filament_colour = #000000;#FFFFFFFF;#FD8008;#449532\n'
        b'; filament_type = PLA;PLA;PLA;PLA\n; printer_model',
    ))
    observer = SliceObserver(tmp_path, settle_seconds=0)
    observer.poll()
    sliced, = observer.poll()
    h = heads()
    for head, color in zip(h, ('#151a1c', '#ffffff', '#ff7f26', '#2b9c70')):
        head['spool']['details'] = dict(color=color, material='PLA')
    h[1]['spool']['remaining_mg'] = 193800
    model = tray_model(enrich(dict(entries=[sliced], latest=sliced['source']), dict(
        printers={'u1': dict(heads=h)}, selected_printer='u1', safety_margin_g=5, accounted={},
    )))
    assert model['status'] == 'ok'
    assert 'Orca' not in model['mapping']
    assert [(m['number'], m['color'], m['channel']) for m in model['materials']] == [(2, '#FFFFFF', '1')]
    assert 'Нужно 4,27 г · После ≈ 189,53 г' in model['heads'][1]['title']
    assert all(head['status'] is None for i, head in enumerate(model['heads']) if i != 1)


def test_artwork_has_four_dots_and_separate_badges():
    neutral=create_tray_icon();ok=create_tray_icon('ok');short=create_tray_icon('shortage')
    assert neutral.size==(64,64) and neutral.getpixel((0,0))[3]==0
    assert len({neutral.getpixel(p) for p in [(16,16),(46,16),(16,46),(46,46)]})==4
    assert neutral.tobytes()!=ok.tobytes()!=short.tobytes()
    assert create_toolhead_menu_icon('#ff8800','ok').startswith(b'\x89PNG')
    assert create_material_menu_icon('#FD8008').startswith(b'\x89PNG')


def test_tray_shows_slice_usage_without_guessed_head_balances():
    e = entry([32.85, 0, 31.01, 8.42, 21.91], plate=3)
    snapshot = enrich(dict(entries=[e], latest=e['source']), dict(
        printers={'u1': dict(heads=heads(100000))}, selected_printer='u1',
        safety_margin_g=5, accounted={},
    ))
    model = tray_model(snapshot)
    assert model['status'] == 'unknown' and '94,19 г' in model['forecast']
    assert 'Стол 3' in model['forecast'] and 'окне подготовки Orca' in model['mapping']
    assert all('после' not in head['title'] for head in model['heads'])
