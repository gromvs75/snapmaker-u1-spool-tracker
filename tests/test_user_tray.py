from tracker_user_tray import tray_model,create_tray_icon,create_toolhead_menu_icon
from tracker_uid_forecast import enrich
from test_uid_forecast import entry,heads


def test_tray_uses_latest_plate_selected_printer_and_tenth_gram():
    e=entry([10.1234,0,0,0]);h=heads(30001)
    snap=enrich(dict(entries=[e],latest=e['source']),dict(printers={'b':dict(name='Мастерская B',heads=h)},
                selected_printer='b',safety_margin_g=5,accounted={}))
    model=tray_model(snap)
    assert model['status']=='ok' and 'Пластина 1' in model['forecast']
    assert '30,0 г' in model['heads'][0]['title'] and '19,9 г' in model['heads'][0]['title']
    assert model['title']=='Мастерская B (4 головки)'
    h[0]['usable']=False
    snap=enrich(dict(entries=[e],latest=e['source']),dict(printers={'b':dict(name='B',heads=h)},
                selected_printer='b',safety_margin_g=5,accounted={}))
    assert tray_model(snap)['status']=='unknown'


def test_artwork_has_four_dots_and_separate_badges():
    neutral=create_tray_icon();ok=create_tray_icon('ok');short=create_tray_icon('shortage')
    assert neutral.size==(64,64) and neutral.getpixel((0,0))[3]==0
    assert len({neutral.getpixel(p) for p in [(16,16),(46,16),(16,46),(46,46)]})==4
    assert neutral.tobytes()!=ok.tobytes()!=short.tobytes()
    assert create_toolhead_menu_icon('#ff8800','ok').startswith(b'\x89PNG')
