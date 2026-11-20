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
    assert model['materials'][0] == dict(number=1, grams=15.08, color='#FD8008')
    assert model['status'] == 'unknown' and all('после' not in head['title'] for head in model['heads'])
    assert '30,0 г' in model['heads'][0]['title'] and model['title'] == 'Мастерская B (4 головки)'


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
    assert 'Стол 3' in model['forecast'] and 'проверяется при запуске' in model['mapping']
    assert all('после' not in head['title'] for head in model['heads'])
