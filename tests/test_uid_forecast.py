from pathlib import Path
from dev.observer_fixture import payload
from tracker_uid_forecast import SliceForecast
from tracker_uid_forecast import forecast_entry, enrich
from tracker_uid_session import Session


def test_before_upload_reslice_removal_and_restart(tmp_path):
    session=Session(tmp_path/'data',allowed_urls=[])
    folder=tmp_path/'slices'/'project'/'Metadata';folder.mkdir(parents=True)
    path=folder/'.42.0.gcode';path.write_bytes(payload('25.1234, 0, 0, 0'))
    forecast=SliceForecast(session,tmp_path/'slices')
    try:
        assert forecast.poll()['entries'][0]['state']=='pending'
        forecast.observer.settle=0
        ready=forecast.poll();assert ready['entries'][0]['weights'][0]==25.1234
        assert not session.connected and session.call('inspect')['jobs']==[]
        Path(str(path)+'.tmp').write_bytes(payload('30, 0, 0, 0'))
        pending=forecast.poll()['entries'][0]
        assert pending['state']=='pending' and 'weights' not in pending
        Path(str(path)+'.tmp').replace(path);forecast.poll()
        assert forecast.poll()['entries'][0]['weights'][0]==30
        restarted=SliceForecast(session,tmp_path/'slices')
        assert restarted.poll()['entries'][0]['state']=='pending'
        path.unlink()
        assert forecast.poll()['entries'][0]['state']=='removed'
        assert forecast.snapshot()['latest'] is None
    finally:session.close()


def heads(remaining=30000, usable=True):
    return [dict(channel=str(i),spool=dict(spool_id=str(i),remaining_mg=remaining,
                name='PLA '+str(i),details={'color':'#abcdef'}),usable=usable,reason='') for i in range(4)]


def entry(weights, **extra):
    return dict(source='project/Metadata/.42.0.gcode',state='ready',weights=weights,
                completed_at_ns=100000000000,observed_at=100,sha256='a'*64,**extra)


def test_two_materials_cannot_claim_physical_heads():
    preview = forecast_entry(entry([15.08, 2.36, 0, 0], colors=['#FD8008', '#000000']))
    assert preview['materials'] == [
        dict(number=1, grams=15.08, color='#FD8008'),
        dict(number=2, grams=2.36, color='#000000'),
    ]
    assert preview['status'] == 'unknown' and preview['requires_mapping']
    assert preview['rows'] == [] and not preview['mapping_assumed']
    assert forecast_entry(entry([0, 0, 0, 0]))['materials'] == []
    assert forecast_entry(dict(source='x', state='pending'))['rows'] == []


def test_color_and_type_forecast_uses_physical_heads_and_checks_reserve():
    h = heads()
    for head, color, remaining, kind in zip(h, ('#151a1c','#ffffff','#ff7f26','#2b9c70'),
                                           (430700,193800,833600,831900), ('PLA','PLA','PLA. +','PLA+')):
        head['spool'].update(remaining_mg=remaining, details=dict(color=color, material=kind))
    e = entry([15.08, 2.36, 0, 0], colors=['#FD8008','#000000'], filament_types=['PLA','PLA'])
    preview = forecast_entry(e,h,5)
    assert preview['status'] == 'ok' and not preview['requires_mapping']
    assert [(r['channel'],r['used'],round(r['after'],2)) for r in preview['rows']] == [
        ('2',15.08,818.52), ('0',2.36,428.34),
    ]

    h[2]['spool']['remaining_mg'] = 15000
    preview = forecast_entry(e,h,5)
    assert preview['status'] == 'shortage' and round(preview['rows'][0]['deficit'],2) == 5.08

    # Two equally matching heads require a choice, even with a full spool.
    h[1]['spool']['details']['color'] = '#ff7f26'
    preview = forecast_entry(e,h,5)
    assert preview['status'] == 'unknown' and preview['requires_mapping']
    assert [choice['channel'] for choice in preview['materials'][0]['choices']] == ['1','2']
    assert [r['channel'] for r in preview['rows']] == ['0']

    h[1]['spool']['details']['material'] = 'ABS'
    h[2]['forecast_usable'] = False
    preview = forecast_entry(e,h,5)
    assert preview['status'] == 'unknown' and not preview['requires_mapping']
    assert preview['rows'][0]['remaining'] is None


def test_forecast_printer_isolation_and_accounted_file_exclusion():
    e=entry([25,0,0,0]);snap=dict(entries=[e],latest=e['source'])
    inv=dict(printers={'a':dict(heads=heads(30000)),'b':dict(heads=heads(29000))},
             selected_printer='b',safety_margin_g=5,accounted={})
    f=enrich(snap,inv)
    assert f['printers']['a']['entries'][0]['materials'] == f['printers']['b']['entries'][0]['materials']
    assert f['printers']['a']['heads'][0]['spool']['remaining_mg'] == 30000
    assert f['printers']['b']['heads'][0]['spool']['remaining_mg'] == 29000
    assert f['selected_printer']=='b'
    inv['accounted']={e['sha256']:101}
    assert enrich(snap,inv)['latest'] is None
    e['completed_at_ns']=102000000000
    assert enrich(snap,inv)['latest']==e['source']


def test_used_fifth_profile_keeps_grams_but_never_assumes_a_head():
    from tracker_desktop_model import forecast_view

    e = entry([32.85, 0, 31.01, 8.42, 21.91], plate=3)
    snapshot = enrich(dict(entries=[e], latest=e['source']), dict(
        printers={'u1': dict(heads=heads(100000))}, selected_printer='u1',
        safety_margin_g=5, accounted={},
    ))
    shown = forecast_view(snapshot, 'u1')['entries'][0]
    assert shown['weights'] == e['weights'] and shown['requires_mapping']
    assert shown['unknown'] and not shown['mapping_assumed'] and shown['rows'] == []


def test_reserve_and_selected_printer_survive_restart(tmp_path):
    s=Session(tmp_path,allowed_urls=[])
    try:
        s.call('save_settings',values={'printers':[dict(id='a',name='A',url='http://127.0.0.1:19811')],
                    'selected_printer':'a','safety_margin_g':'10.123'},expected_revision=s.call('settings')['revision'])
    finally:s.close()
    s=Session(tmp_path,allowed_urls=[])
    try:
        value=s.call('forecast_inventory')
        assert value['selected_printer']=='a' and value['safety_margin_g']==10.123
        assert s.call('inspect')['debits']==[] and not s.connected
    finally:s.close()
