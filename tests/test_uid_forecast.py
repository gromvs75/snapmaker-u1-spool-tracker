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


def test_reserve_combined_heads_threshold_and_unknown():
    h=heads();h[1]['spool']=dict(h[0]['spool'])
    r=forecast_entry(entry([10,15,0,0]),h,5)
    assert r['status']=='ok' and r['rows'][0]['after']==5
    h[0]['spool']['remaining_mg']=29999;h[1]['spool']['remaining_mg']=29999
    r=forecast_entry(entry([10,15,0,0]),h,5)
    assert r['status']=='shortage' and abs(r['rows'][0]['deficit']-.001)<1e-9
    h[0]['usable']=False
    assert forecast_entry(entry([10,0,0,0]),h,5)['status']=='unknown'
    assert forecast_entry(entry([0,0,0,0]),h,5)['status']=='unknown'
    assert forecast_entry(dict(source='x',state='pending'),h,5)['rows']==[]


def test_forecast_printer_isolation_and_accounted_file_exclusion():
    e=entry([25,0,0,0]);snap=dict(entries=[e],latest=e['source'])
    inv=dict(printers={'a':dict(heads=heads(30000)),'b':dict(heads=heads(29000))},
             selected_printer='b',safety_margin_g=5,accounted={})
    f=enrich(snap,inv)
    assert f['printers']['a']['entries'][0]['status']=='ok'
    assert f['printers']['b']['entries'][0]['status']=='shortage'
    assert f['selected_printer']=='b'
    inv['accounted']={e['sha256']:101}
    assert enrich(snap,inv)['latest'] is None
    e['completed_at_ns']=102000000000
    assert enrich(snap,inv)['latest']==e['source']


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
