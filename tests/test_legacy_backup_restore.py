import copy
import json
import sqlite3
from pathlib import Path

import pytest
from backup import create_backup
from storage import Store
from spoolman_bridge import blank, remote_id
from tracker_uid_session import Session
from tracker_uid_sender import Sender


@pytest.fixture
def old_backup(tmp_path):
    store = Store(tmp_path/'old-synthetic')
    url = 'http://127.0.0.1:19999'
    rid = remote_id(url,42)
    def seed(data):
        data.update(language='de',safety_margin_g=10)
        data['printer'].update(host='127.0.0.1',port=19991,enabled=True,guard_mode='strict')
        data['spoolman'] = dict(blank(),url=url,mode='send',epoch='old-epoch')
        data['spools'] = {'local':dict(name='Original PLA',material='PLA',remaining_g=125.259,color='#ff7700',
                                     calibration=dict(diameter_mm=1.751,density_g_cm3=1.244)),
                          rid:dict(name='Remote PETG',material='PETG',remaining_g=500.123,spoolman=dict(url=url,id=42))}
        data['slots'].update({'1':'local','2':rid})
        for i,state in enumerate(('committed','committed','review','cancelled','review')):
            plan = dict(filename=f'saved-{i}.gcode',sha256=str(i)*64,size=100,weights=[12,0,0,0],
                        spool_ids=['local','','',''],created_at=1000+i,status=state,printer=dict(data['printer']))
            if i==3:plan['printer']['port']=19992
            data['plans'][str(i)] = plan
            run = dict(job_id=str(i),plan_id=str(i),start_time=2000+i,status=state,filename=plan['filename'])
            if i!=4:run.update(physical_weights=[12,0,0,0],physical_spool_ids=['local','','',''],tool_mapping=[0,1,2,3])
            if i==1:
                run.update(accounting_method='manual_review',manual_consumption={rid:3})
                data['spoolman']['outbox']['old-op'] = dict(job='run-1',local_id=rid,url=url,spool_id=42,grams=3,created_at=2001,state='pending')
            if i==2:run.update(review_reason='Connection lost during pause',replenishment_observed=True)
            data['runs']['run-'+str(i)] = run
    store.update(seed)
    return create_backup(store,'1.3.3')


def restore(app, package):
    preview = app.call('validate_backup',package=package)
    return app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)


def test_import_preserves_balances_details_history_and_restart(tmp_path,old_backup,monkeypatch):
    # No network method is permitted during conversion, restore or replays.
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('Unexpected network'))
    original = copy.deepcopy(old_backup)
    directory = tmp_path/'app'
    app = Session(directory,allowed_urls=[])
    try:
        app.call('register','04112233','Before restore',42000)
        initial = app.call('inspect')
        preview = app.call('validate_backup',package=old_backup)
        assert preview['source_format']=='legacy' and preview['source_version']=='1.3.3'
        assert (preview['spools'],preview['jobs'],preview['debits'],preview['remote_operations'])==(2,5,2,1)
        assert app.call('inspect')==initial and not list(directory.glob('before-restore-*'))
        result = restore(app,old_backup)
        rollback = json.loads((directory/result['rollback_file']).read_text())
        assert app.call('validate_backup',package=rollback)['spools']==1
        settings = app.call('settings')['values']
        assert settings['language']=='de' and settings['safety_margin_g']==10
        assert settings['spoolman_mode']=='off' and len(settings['printers'])==2
        assert set(settings['guard_modes'].values())=={'warn'}
        assert not app.connected
        rows = app.call('library_snapshot')['spools']
        assert {r['spool_id']:r['remaining_mg'] for r in rows}=={sid:round(s['remaining_g']*1000) for sid,s in old_backup['data']['spools'].items()}
        assert all(r['uid'] is None for r in rows)
        local = next(r for r in rows if r['spool_id']=='local')
        assert local['details']['calibration']==dict(diameter_mm=1.751,density_g_cm3=1.244)
        assert local['details']['color']=='#ff7700'
        assert all(not a['confirmed'] for a in app.call('inspect')['manual_assignments'])
        desktop = app.call('desktop_snapshot')
        assert len(desktop['runs'])==4
        assert sum(r['accounted_g'] for r in desktop['runs'].values())==15
        review = next(d for d in desktop['saved_history'].values() if d['filename']=='saved-2.gcode')
        assert review['plan'][0]['planned_mg']==12000 and review['plan'][0]['spool_id']=='local'
        assert review['quarantined'] and review['candidates'][0]['suggested_additional_mg'] is None
        assert 'Connection lost during pause' in review['reasons']
        unverified = next(d for d in desktop['saved_history'].values() if d['filename']=='saved-4.gcode')
        assert not unverified['plan'][0]['mapping_verified']
        before = app.call('inspect')['debits']
        for _ in range(3):
            for i in (0,1,2,4):
                app.call('history',settings['selected_printer'],[dict(job_id=str(i),start_time=float(2000+i),filename=f'saved-{i}.gcode',status='completed')])
        assert app.call('inspect')['debits']==before
        assert app.call('desktop_statistics')['total_mg']==15000
        assert app.call('delivery_list')[0]['state']=='uncertain'
        sender=Sender(app,[settings['spoolman_url']],client_factory=lambda *_:pytest.fail('No send'))
        assert sender.send_one()=='disabled'
        app.call('save_settings',values=dict(spoolman_mode='send'),expected_revision=app.call('settings')['revision'])
        assert sender.send_one()=='blocked'
        app.call('save_settings',values=dict(spoolman_mode='off'),expected_revision=app.call('settings')['revision'])
        newer = app.call('backup_package')
        assert app.call('validate_backup',package=newer)['jobs']==5
    finally:app.close()
    app = Session(directory,allowed_urls=[])
    try:
        assert app.call('settings')['values']==settings and not app.connected
        assert app.call('inspect')['debits']==before
        assert app.call('delivery_list')[0]['state']=='uncertain'
        assert restore(app,newer)['jobs']==5
        assert app.call('inspect')['debits']==before
        # Rollback is also a normal 2.0 backup, including the original UID.
        restore(app,rollback)
        assert app.call('inspect')['spools'][0]['uid']=='04112233'
    finally:app.close()
    assert old_backup==original


def test_imported_unaccounted_print_manual_additional_amount_is_once(tmp_path,old_backup):
    app = Session(tmp_path/'app',allowed_urls=[])
    try:
        restore(app,old_backup)
        d = next(d for d in app.call('desktop_snapshot')['saved_history'].values() if d['filename']=='saved-2.gcode')
        request=dict(job_key=d['job']['job_key'],action='account',expected_revision=d['revision'],
                     request_id='imported-manual-review',confirmed=True,completed=True,allocations_mg={'local':3500},note='Verified real completion on fixture')
        assert app.call('history_decide',**request)['status']=='saved'
        assert app.call('history_decide',**request)['status']=='duplicate'
        assert next(s for s in app.call('inspect')['spools'] if s['spool_id']=='local')['remaining_mg']==121759
        pid=d['job']['printer_id']
        for _ in range(3):app.call('history',pid,[dict(job_id='2',start_time=2002.,filename='saved-2.gcode',status='completed')])
        assert next(s for s in app.call('inspect')['spools'] if s['spool_id']=='local')['remaining_mg']==121759
        assert app.call('history_detail',d['job']['job_key'])['accounted_mg']==3500
    finally:app.close()


@pytest.mark.parametrize('kind',['version','missing','nan','duplicate_history','duplicate_remote','bad_reference'])
def test_invalid_legacy_backup_does_not_change_live_state(tmp_path,old_backup,kind):
    bad=copy.deepcopy(old_backup)
    if kind=='version':bad['backup_version']=99
    elif kind=='missing':del bad['data']['plans']
    elif kind=='nan':bad['data']['spools']['local']['remaining_g']=float('nan')
    elif kind=='duplicate_history':bad['data']['runs']['duplicate']=copy.deepcopy(bad['data']['runs']['run-0'])
    elif kind=='duplicate_remote':bad['data']['spoolman']['outbox']['duplicate']=copy.deepcopy(bad['data']['spoolman']['outbox']['old-op'])
    else:bad['data']['slots']['1']='missing'
    app=Session(tmp_path/'app',allowed_urls=[])
    try:
        app.call('register_manual','Untouched',4321)
        revision=app.call('validate_backup',package=old_backup)['current_revision']
        with pytest.raises(ValueError):app.call('restore_backup',package=bad,expected_revision=revision,confirmed=True)
        assert app.call('inspect')['spools'][0]['remaining_mg']==4321
        assert not list(app.directory.glob('before-restore-*'))
    finally:app.close()


def test_legacy_restore_stale_and_missing_confirmation(tmp_path,old_backup):
    app=Session(tmp_path/'app',allowed_urls=[])
    try:
        revision=app.call('validate_backup',package=old_backup)['current_revision']
        with pytest.raises(ValueError):app.call('restore_backup',package=old_backup,expected_revision=revision)
        app.call('register_manual','New',1111)
        with pytest.raises(ValueError):app.call('restore_backup',package=old_backup,expected_revision=revision,confirmed=True)
        assert app.call('inspect')['spools'][0]['remaining_mg']==1111
    finally:app.close()


def test_old_remote_operation_requires_explicit_review_and_old_backup_cannot_resend(tmp_path,old_backup):
    from test_uid_delivery import Fake, decision
    app=Session(tmp_path/'app',allowed_urls=[])
    try:
        restore(app,old_backup)
        app.call('save_settings',values=dict(spoolman_mode='send'),expected_revision=app.call('settings')['revision'])
        remote=Fake();sender=Sender(app,['http://127.0.0.1:19999'],client_factory=lambda _:remote)
        assert sender.send_one()=='blocked' and not remote.writes
        decision(app,'not_applied',note='Verified absent at synthetic server')
        approved=app.call('backup_package')
        assert sender.send_one()=='sent' and remote.writes==[{'use_weight':3}]
        assert sender.send_one()=='idle'
        restore(app,approved)
        for _ in range(3):assert sender.send_one()=='blocked'
        assert remote.writes==[{'use_weight':3}]
        decision(app,'applied',request_id='resolved-after-restore',note='Verified previous delivery')
        assert sender.send_one()=='idle' and len(remote.writes)==1
        assert app.call('desktop_statistics')['total_mg']==15000
    finally:app.close()


def test_accessory_policy_is_set_after_cocoa_import_and_before_gui(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from test_uid_port_shell import Event
    from tracker_uid_window import UidWindow
    calls=[]
    window=SimpleNamespace(events=SimpleNamespace(shown=Event(),closing=Event()))
    webview=SimpleNamespace(create_window=lambda *a,**k:window,start=lambda **k:calls.append('gui'))
    tray=SimpleNamespace(run_detached=lambda:calls.append('tray'),stop=lambda:calls.append('stop'))
    monkeypatch.setitem(sys.modules,'pystray',SimpleNamespace(Icon=lambda *a,**k:tray,Menu=lambda *a:a,MenuItem=lambda *a,**k:None))
    monkeypatch.setitem(sys.modules,'webview.platforms',SimpleNamespace(cocoa=object()))
    monkeypatch.setitem(sys.modules,'AppKit',SimpleNamespace(NSApplicationActivationPolicyAccessory=1,
        NSApplication=SimpleNamespace(sharedApplication=lambda:SimpleNamespace(setActivationPolicy_=lambda v:calls.append(('policy',v))))))
    monkeypatch.setattr('macos_menu.configure_accessory_panel',lambda cocoa:calls.append('panel'))
    monkeypatch.setattr(sys,'platform','darwin')
    UidWindow('http://127.0.0.1:1',tmp_path,webview_module=webview).run()
    assert calls==['tray','panel',('policy',1),'gui','stop']


def test_legacy_backup_full_shell_preview_languages_and_history(tmp_path,old_backup):
    import threading
    from playwright.sync_api import sync_playwright
    from tracker_uid_gui import serve
    app=Session(tmp_path/'app',allowed_urls=[])
    server=serve(app,app.fleet)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    saved=tmp_path/'backup-1.3.3.json';saved.write_text(json.dumps(old_backup))
    screens=Path('output/legacy-backup-ui');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1300,height=1040))
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            for lang,phrase in [('en','1.x backup'),('de','Sicherung 1.x'),('uk','Копія 1.x'),('es','Copia 1.x'),('ru','Копия 1.x')]:
                page.locator('#lang-picker').select_option(lang)
                page.locator('#nav-settings').click();page.locator('[data-settings-section=backup]').click()
                page.locator('#backup-import').click();page.locator('#desktop-backup-file').set_input_files(saved)
                with page.expect_response('**/api/validate_backup') as response:page.locator('#desktop-backup-check').click()
                assert response.value.ok
                assert page.locator('#desktop-backup-dialog').get_by_text(phrase,exact=False).is_visible()
                assert page.locator('#desktop-backup-apply').is_disabled()
                if lang!='ru':page.locator('#desktop-backup-close').click()
            page.screenshot(path=str(screens/'legacy-preview.png'),full_page=True)
            page.locator('#desktop-backup-ack').check()
            with page.expect_response('**/api/restore_backup') as response:page.locator('#desktop-backup-apply').click()
            assert response.value.ok and response.value.json()['source_version']=='1.3.3'
            page.locator('#desktop-backup-dialog').wait_for(state='hidden')
            page.wait_for_function("document.getElementById('lang-picker').value==='de'")
            page.locator('#lang-picker').select_option('ru')
            page.locator('#nav-history').click()
            page.wait_for_function("Object.values(desktopFormData.runs).some(r=>r.filename==='saved-2.gcode')")
            # Open the actual history row, using its saved key rather than a live printer.
            page.get_by_role('button',name='Раскрыть задание').first.click()
            page.locator('#uid-history-dialog').wait_for(state='visible')
            assert page.locator('#uid-history-dialog').inner_text().find('12')>=0
            page.screenshot(path=str(screens/'imported-history.png'),full_page=True)
            assert not errors and not app.connected
            assert app.call('delivery_list')[0]['state']=='uncertain'
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();app.close()
