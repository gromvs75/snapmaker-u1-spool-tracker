from pathlib import Path
from dev.observer_fixture import payload
from tracker_uid_forecast import SliceForecast
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
