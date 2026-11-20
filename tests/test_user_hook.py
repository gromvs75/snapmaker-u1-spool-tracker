import json
import threading
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_user_hook import handle_slicer_hook,describe
from dev.observer_fixture import payload
import pytest


def test_postprocessor_closed_app_cancel_save_and_restart(tmp_path):
    gcode=tmp_path/'a.gcode';gcode.write_bytes(payload('2.3456,0,0,0'))
    directory=tmp_path/'profile';dialogs=[]
    assert handle_slicer_hook(directory,gcode,dialog=lambda *a,**k:False)==1
    assert handle_slicer_hook(directory,gcode,output_name='Part.gcode',dialog=lambda *a,**k:dialogs.append(a) or True)==0
    session=Session(directory,allowed_urls=[])
    try:
        state=session.call('library_snapshot');plan=state['export_plans'][0]
        assert plan['filename']=='Part.gcode' and plan['weights'][0]==2.3456 and not plan['mapping_assumed']
        message = dialogs[0][0]
        assert 'Материал 1 · 2,3456 г' in message and 'T0' not in message
        assert session.call('inspect')['debits']==[] and not session.connected
    finally:session.close()


def test_live_hook_uses_existing_owner_no_second_writer(tmp_path):
    directory=tmp_path/'profile';session=Session(directory,allowed_urls=[])
    calls=[];server=serve(session,session.fleet,window_action=lambda a:calls.append(a))
    thread=threading.Thread(target=server.serve_forever);thread.start()
    (directory/'instance.json').write_text(json.dumps(dict(port=server.server_port,token=server.tracker_token)))
    path=tmp_path/'slice.gcode';path.write_bytes(payload('4,0,0,0'))
    owner_id=session.call('inspect')['thread_id']
    try:
        for _ in range(2):assert handle_slicer_hook(directory,path,dialog=lambda *a,**k:True)==0
        assert session.call('inspect')['thread_id']==owner_id
        assert len(session.call('library_snapshot')['export_plans'])==1
        assert session.call('inspect')['debits']==[] and not session.connected
        from tracker_user_hook import instance_call
        instance_call(directory,'window',{'action':'show'});assert calls==['show']
        package=session.call('backup_package')
        preview=session.call('validate_backup',package=package)
        session.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
        assert len(session.call('library_snapshot')['export_plans'])==1
        assert session.call('inspect')['debits']==[]
    finally:server.shutdown();thread.join();server.server_close();session.close()


def test_export_revision_rejects_changed_reserve_and_missing_file(tmp_path):
    path=tmp_path/'slice.gcode';path.write_bytes(payload('4,0,0,0'))
    s=Session(tmp_path/'profile',allowed_urls=[])
    try:
        plan=describe(path);p=s.call('export_preview',plan=plan)
        s.call('save_settings',values={'safety_margin_g':10},expected_revision=s.call('settings')['revision'])
        with pytest.raises(ValueError,match='изменились'):
            s.call('export_save',plan=plan,expected_revision=p['revision'],confirmed=True)
        assert not s.call('library_snapshot')['export_plans']
    finally:s.close()
    assert handle_slicer_hook(tmp_path/'missing-profile',tmp_path/'missing',dialog=lambda *a,**k:False)==1
    assert not (tmp_path/'missing-profile').exists()
