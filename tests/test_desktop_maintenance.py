import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright
from tracker_desktop_files import BackupFiles
from tracker_desktop_statistics import statistics
from tracker_uid_gui import serve
from tracker_uid_session import Session
from tracker_uid_library import Library
from tracker_uid_history_review import HistoryReview
from tracker_uid_motion_lifecycle import MotionLifecycle
from test_desktop_inventory import inventory, perform, intent, spool, slots
from test_desktop_services import Fleet
from test_uid_motion_adapter import bench
from test_uid_delivery import bench as delivery_bench, URL
from tracker_uid_sender import Sender


def test_parameters_archive_preserve_identity_precision_and_guards(inventory):
    l,d,f=inventory
    sid=l.create('Exact PLA',125.259,fleet=f)['spool_id']
    req=intent(l,f,'spools/calibration',dict(id=sid,calibration=dict(diameter_mm='1.751',density_g_cm3='1.244')))
    d.execute(**req,fleet=f);assert d.execute(**req,fleet=f)['status']=='duplicate'
    assert spool(l,sid)['details']['calibration']==dict(diameter_mm=1.751,density_g_cm3=1.244)
    for bad in ({'uid':'04112233'}, {'diameter_mm':'nan','density_g_cm3':1.2},{'diameter_mm':1.75,'density_g_cm3':True}):
        with pytest.raises(ValueError):perform(l,d,f,'spools/calibration',dict(id=sid,calibration=bad))
    perform(l,d,f,'slots',slots(sid))
    with pytest.raises(ValueError):perform(l,d,f,'spools/archive',dict(id=sid,archived=True))
    key=l.accounting.begin('a','partial','1010',['0'],'test',f)
    l.accounting.apply(key,0,{'0':101},state='active',source='test',basis='motion_estimate')
    with pytest.raises(ValueError):perform(l,d,f,'spools/calibration',dict(id=sid,calibration=dict(diameter_mm=2.,density_g_cm3=1.3)))
    l.accounting.apply(key,1,{'0':2983},state='cancelled',source='test',basis='motion_estimate')
    perform(l,d,f,'slots',slots())
    archive=intent(l,f,'spools/archive',dict(id=sid,archived=True))
    d.execute(**archive,fleet=f);assert d.execute(**archive,fleet=f)['status']=='duplicate'
    with pytest.raises(ValueError):perform(l,d,f,'slots',slots(sid))
    assert spool(l,sid)['remaining_mg']==122276
    assert l.accounting.apply(key,1,{'0':2983},state='cancelled',source='test',basis='motion_estimate')=='duplicate'
    perform(l,d,f,'spools/archive',dict(id=sid,archived=False))
    assert spool(l,sid)['remaining_mg']==122276
    # A tagged archived spool is still recognized by identity but cannot feed.
    tagged=l.catalog.register('04112233','UID',2000)
    perform(l,d,f,'spools/archive',dict(id=tagged['spool_id'],archived=True))
    f['a']['channels']['0']=dict(state='present',uid='04112233')
    row=l.catalog.reconcile(f)[0];assert row['state']=='archived' and not row['usable']


def test_statistics_include_partial_cancelled_and_mixed_manual_once(bench):
    _,catalog,fleet,adapter=bench
    MotionLifecycle(adapter);accounting=adapter.service.accounting;l=Library(accounting);HistoryReview(accounting)
    l.save_settings(dict(printers=[dict(id=p,name=p,url='http://127.0.0.1:'+str(19000+i)) for i,p in enumerate(('a','b'))],selected_printer='a'),l.settings()['revision'])
    a=accounting.begin('a','partial','1010',['0'],'test',fleet.snapshot())
    accounting.apply(a,0,{'0':100},state='active',source='test',basis='motion_estimate')
    b=accounting.begin('b','cancel','1020',['1'],'test',fleet.snapshot())
    accounting.apply(b,0,{'1':200},state='cancelled',source='test',basis='motion_estimate')
    first=statistics(l);assert first['total_mg']==100 and first['head_mg']==[100,0,0,0]
    accounting.apply(a,1,{'0':250},state='completed',source='test',basis='completed_gcode')
    assert accounting.apply(a,1,{'0':250},state='completed',source='test',basis='completed_gcode')=='duplicate'
    result=statistics(l);assert result['total_mg']==250 and result['by_basis']=={'motion_estimate':100,'completed_gcode':150}
    assert sum(result['by_spool'].values())==sum(result['by_month'].values())==250
    # Preserve the basis of earlier debits when a later remainder is manual.
    c=accounting.begin('a','manual-rest','1030',['0'],'test',fleet.snapshot())
    accounting.apply(c,0,{'0':100},state='active',source='test',basis='motion_estimate')
    adapter.observation_gap('a','sleep')
    review=HistoryReview(accounting);detail=review.detail(c);sid=detail['candidates'][0]['spool_id']
    review.decide(c,'account',detail['revision'],'manual-remaining',confirmed=True,completed=True,allocations_mg={sid:50},note='Verified finished',fleet={})
    mixed=statistics(l)
    assert mixed['total_mg']==400 and mixed['by_basis']['manual_reconciliation']==50
    assert mixed['head_mg']==[350,0,0,0] and mixed['unattributed_mg']==50
    l.save_settings(dict(selected_printer='b'),l.settings()['revision'])
    assert statistics(l)['total_mg']==200 and statistics(l)['counts']=={'cancelled':1}


def test_native_backup_files_cancel_save_read_bounded(tmp_path):
    path=tmp_path/'copy.json';selected=[];calls=[]
    class Window:
        def create_file_dialog(self,*args,**kwargs):calls.append((args,kwargs));return selected
    files=BackupFiles(lambda:Window(),SimpleNamespace(SAVE_DIALOG=1,OPEN_DIALOG=2))
    assert files('export',{})['status']=='cancelled' and not path.exists()
    selected.append(str(path));assert files('export',{'fixture':1})['status']=='ok'
    assert files('select')['package']=={'fixture':1}
    assert calls[-1][1]==dict(allow_multiple=False)
    path.write_text('not JSON')
    with pytest.raises(ValueError):files('select')
    assert path.read_text()=='not JSON'


def test_native_backup_returns_to_accessory_window_after_select_cancel_or_error():
    calls=[]
    class Window:
        def create_file_dialog(self,*args,**kwargs):
            calls.append('dialog')
            if len(calls)>2:raise RuntimeError('Closed picker')
            return []
    files=BackupFiles(lambda:Window(),SimpleNamespace(SAVE_DIALOG=1,OPEN_DIALOG=2),on_dialog_closed=lambda:calls.append('show'))
    assert files('select')['status']=='cancelled'
    assert calls==['dialog','show']
    with pytest.raises(RuntimeError):files('select')
    assert calls==['dialog','show','dialog','show']


def test_full_shell_parameters_archive_statistics_backup_and_restart(tmp_path,delivery_bench):
    directory=tmp_path/'app';app=Session(directory,allowed_urls=[],fleet_factory=Fleet)
    original,remote,_,_,_,_=delivery_bench
    seed=original.call('backup_package');validation=app.call('validate_backup',package=seed)
    app.call('restore_backup',package=seed,expected_revision=validation['current_revision'],confirmed=True)
    op=app.call('delivery_list')[0]
    app.call('delivery_decide',op['operation_id'],op['revision'],'not_applied','Verified no delivery','rearm-fixture',True)
    sender=Sender(app,[URL],client_factory=lambda _:remote)
    printers=[dict(id=p,name='Bench '+p,url='http://127.0.0.1:'+str(19200+i)) for i,p in enumerate(('a','b'))]
    app.call('save_settings',values=dict(printers=printers,selected_printer='a'),expected_revision=app.call('settings')['revision'])
    sid=app.call('create_spool','Exact PLA','125.259',details=dict(material='PLA',color='#ff7700'))['spool_id']
    initial_count=len(app.call('library_snapshot')['spools'])
    server=serve(app,app.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
    screens=Path('output/full-133-maintenance-ui');screens.mkdir(parents=True,exist_ok=True)
    errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1360,height=1080));page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#nav-spools').click()
            page.wait_for_function('(n)=>desktopFormData?.spools && Object.keys(desktopFormData.spools).length===n',arg=initial_count)
            for lang,caption in [('en','Archive'),('de','Archiv'),('uk','Архів'),('es','Archivo'),('ru','Архив')]:
                page.locator('#lang-picker').select_option(lang)
                page.wait_for_function('(caption)=>document.getElementById("desktop-archive-view").parentElement.textContent===caption',arg=caption)
            page.evaluate('(sid)=>window.inventoryParameters(sid)',sid)
            page.locator('#cal-diameter').fill('1.751');page.locator('#cal-density').fill('1.244')
            page.screenshot(path=str(screens/'parameters.png'),full_page=True)
            with page.expect_response('**/api/desktop/spools/calibration') as r:page.locator('#cal-save').click()
            assert r.value.ok
            page.locator('#inventory-param-dialog').wait_for(state='hidden')
            row=page.locator(f'#spools-table tr[data-spool-id="{sid}"]')
            with page.expect_response('**/api/desktop/spools/archive') as r:row.locator('.desktop-archive-action').click()
            assert r.value.ok
            page.wait_for_function('(sid)=>desktopFormData.spools[sid].archived===true',arg=sid)
            assert not row.is_visible();page.locator('#desktop-archive-view').check();assert row.is_visible()
            page.screenshot(path=str(screens/'archive.png'),full_page=True)
            page.locator('#nav-history').click();page.locator('#desktop-statistics summary').click()
            page.wait_for_function('document.getElementById("desktop-statistics-body").textContent.includes("Bench a")')
            page.screenshot(path=str(screens/'statistics.png'),full_page=True)
            page.locator('#nav-settings').click();page.locator('[data-settings-section=backup]').click()
            with page.expect_download() as download:page.locator('#backup-export').click()
            saved=tmp_path/'backup.json';download.value.save_as(saved);package=json.loads(saved.read_text());assert package['format']=='tracker-uid-backup'
            assert sender.send_one()=='sent' and len(remote.writes)==1
            app.call('create_spool','Added later',10)
            page.locator('#backup-import').click();page.locator('#desktop-backup-file').set_input_files(saved)
            with page.expect_response('**/api/validate_backup') as r:page.locator('#desktop-backup-check').click()
            assert r.value.ok and r.value.json()['spools']==initial_count
            assert page.locator('#desktop-backup-apply').is_disabled()
            page.screenshot(path=str(screens/'restore-preview.png'),full_page=True)
            # Changed file invalidates previously checked data, including confirmation.
            bad=tmp_path/'corrupt.json';bad.write_text(json.dumps(dict(package,sha256='0'*64)))
            page.locator('#desktop-backup-file').set_input_files(bad)
            with page.expect_response('**/api/validate_backup') as r:page.locator('#desktop-backup-check').click()
            assert r.value.status==409 and page.locator('#desktop-backup-apply').is_disabled()
            assert len(app.call('library_snapshot')['spools'])==initial_count+1
            page.locator('#desktop-backup-file').set_input_files(saved)
            with page.expect_response('**/api/validate_backup'):page.locator('#desktop-backup-check').click()
            page.locator('#desktop-backup-ack').check()
            with page.expect_response('**/api/restore_backup') as r:page.locator('#desktop-backup-apply').click()
            assert r.value.ok;rollback=r.value.json()['rollback_file']
            page.locator('#desktop-backup-dialog').wait_for(state='hidden')
            assert app.call('validate_backup',package=json.loads((directory/rollback).read_text()))['spools']==initial_count+1
            assert len(app.call('library_snapshot')['spools'])==initial_count and not app.connected
            assert sender.send_one()=='blocked' and len(remote.writes)==1
            assert app.call('desktop_statistics')['total_mg']==298
            assert not errors
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();app.close()
    reopened=Session(directory,allowed_urls=[])
    try:
        s=next(s for s in reopened.call('library_snapshot')['spools'] if s['spool_id']==sid)
        assert s['remaining_mg']==125259 and s['details']['archived'] is True
        assert s['details']['calibration']==dict(diameter_mm=1.751,density_g_cm3=1.244)
        assert reopened.call('settings')['values']['language']=='ru'
        assert reopened.call('desktop_statistics')['total_mg']==298
        assert reopened.call('delivery_list')[0]['state']=='uncertain'
    finally:reopened.close()


def test_native_backup_http_uses_current_owner_and_explicit_file_selection(tmp_path):
    import urllib.request
    selected=[]
    class Window:
        def create_file_dialog(self,*args,**kwargs):return selected
    files=BackupFiles(lambda:Window(),SimpleNamespace(SAVE_DIALOG=1,OPEN_DIALOG=2))
    app=Session(tmp_path/'profile',allowed_urls=[])
    app.call('create_spool','Native roundtrip','12.345')
    server=serve(app,app.fleet,backup_file=files);thread=threading.Thread(target=server.serve_forever);thread.start()
    def request(action):
        raw=json.dumps({'action':action}).encode()
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/desktop/backup_file',data=raw,headers={'X-Tracker-Token':server.tracker_token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:return json.load(response)
    try:
        assert request('export')['status']=='cancelled'
        path=tmp_path/'native-copy.json';selected.append(str(path))
        assert request('export')['status']=='ok'
        package=request('select')['package']
        assert app.call('validate_backup',package=package)['spools']==1
        assert app.call('inspect')['spools'][0]['remaining_mg']==12345
    finally:server.shutdown();thread.join();server.server_close();app.close()


def test_archive_queue_and_candidate_guards(inventory):
    from tracker_uid_tags import Tags
    l,d,f=inventory;sid=l.create('Remote',100,fleet=f)['spool_id']
    with l.db:
        l.db.execute("INSERT INTO uid_remote_outbox VALUES('old',1,?,'http://127.0.0.1:18899',42,100,'uncertain')",(sid,))
    with pytest.raises(ValueError,match='Spoolman'):perform(l,d,f,'spools/archive',dict(id=sid,archived=True))
    with l.db:l.db.execute("UPDATE uid_remote_outbox SET state='sent'")
    perform(l,d,f,'spools/archive',dict(id=sid,archived=True))
    tags=Tags(l.accounting)
    with pytest.raises(ValueError,match='архива'):tags._candidate(dict(l.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()),'a','0')
    assert l.db.execute('SELECT state FROM uid_remote_outbox').fetchone()[0]=='sent'
