import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading

from playwright.sync_api import sync_playwright
from tracker_desktop_133 import published_html
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_uid_motion_adapter import bench
from test_uid_recovery import prepare


def test_complete_published_presentation_provenance_no_old_store():
    root=Path(__file__).resolve().parents[1]/'src/tracker_desktop_133'
    manifest=json.loads((root/'ORIGIN.json').read_text())
    assert manifest['commit']=='fdeb1aa11c64bd9a06344c9bcc6433c6bcce4bb1'
    for name,digest in manifest['files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
    before=set(sys.modules)
    html=published_html()
    assert not ({'spool_tracker'} & (set(sys.modules)-before))
    for marker in ('lang-picker','view-overview','view-spools','view-history','view-settings','inventory-create-assign','sm-connect','backup-export','forecast-plate','cal-form','heads-read'):
        assert marker in html,marker
    for language in ('en','ru','de','uk','es'):assert f'value="{language}"' in html


def test_full_frontend_languages_offline_plan_manual_account_and_restart(bench,tmp_path):
    life,key,c=prepare(bench)
    c.db.execute('UPDATE uid_spools SET remaining_mg=125260');c.db.commit()
    directory=tmp_path/'profile';directory.mkdir()
    copy=sqlite3.connect(directory/'tracker.sqlite');c.db.backup(copy);copy.close()
    session=Session(directory,allowed_urls=[])
    session.call('save_settings',values={'printers':[dict(id='a',name='Workshop',url='http://127.0.0.1:19845')]},expected_revision=session.call('settings')['revision'])
    server=serve(session,session.fleet,app_info={'version':'2.0.0rc1','mode':'user'})
    thread=threading.Thread(target=server.serve_forever);thread.start()
    errors=[];screens=Path('output/full-133-integration-ui');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1050})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#uid-history-dialog[open]').wait_for()
            assert 'Печать завершилась успешно?' in page.locator('#uid-history-dialog').inner_text()
            assert '1 г' in page.locator('.uid-saved-plan').inner_text()
            page.get_by_role('button',name='Закрыть',exact=True).click()
            for language,overview,forecast_title in [('en','Overview','Slice forecast'),('de','Übersicht','Slicing-Prognose'),('uk','Огляд','Прогноз нарізки'),('es','Resumen','Previsión del laminado'),('ru','Обзор','Прогноз нарезки')]:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(value)=>currentLang===value',arg=language)
                assert page.locator('#nav-overview').inner_text()==overview
                page.wait_for_function('(title)=>document.getElementById("forecast-heading").textContent===title',arg=forecast_title)
                assert session.call('settings')['values']['language']==language
                page.locator('#nav-settings').click()
                assert page.locator('#view-settings').is_visible()
            page.locator('#nav-overview').click();page.screenshot(path=str(screens/'overview.png'),full_page=True)
            assert '125,3' in page.locator('.head-remaining').first.inner_text()
            page.locator('#nav-spools').click();page.screenshot(path=str(screens/'spools.png'),full_page=True)
            assert page.locator('#spools-table input[type=number]').first.input_value()=='125.26'
            before=session.call('library_snapshot')['spools']
            status=page.evaluate("async id=>(await fetch('/api/spools/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})).status",before[0]['spool_id'])
            assert status==409 and session.call('library_snapshot')['spools']==before
            page.locator('#nav-history').click();page.get_by_role('button',name='Раскрыть задание',exact=True).click()
            page.screenshot(path=str(screens/'history-plan.png'),full_page=True)
            page.get_by_role('button',name='Да — проверить списание',exact=True).click()
            page.locator('.uid-extra-amount').fill('0.750');page.locator('#uid-review-note').fill('Проверено завершённое задание')
            page.locator('#uid-review-ack').check()
            lost=[]
            def lose_response(route):
                if not lost:
                    response=route.fetch();assert response.ok;lost.append(True);route.abort()
                else:route.continue_()
            page.route('**/api/history_decide',lose_response)
            with page.expect_event('requestfailed',predicate=lambda r:r.url.endswith('/api/history_decide')):
                page.locator('#uid-review-apply').click()
            assert sum(d['delta_mg'] for d in session.call('inspect')['debits'])==750
            page.locator('#uid-review-apply').click()
            page.wait_for_function("!document.getElementById('uid-history-dialog').open")
            assert sum(d['delta_mg'] for d in session.call('inspect')['debits'])==750
            page.reload();page.locator('#lang-picker').wait_for()
            assert page.locator('#lang-picker').input_value()=='ru'
            assert page.locator('#uid-history-dialog[open]').count()==0
            assert not errors,errors
            browser.close()
        assert not session.connected
        copy=session.call('backup_package');checked=session.call('validate_backup',package=copy)
        session.call('restore_backup',package=copy,expected_revision=checked['current_revision'],confirmed=True)
        assert sum(d['delta_mg'] for d in session.call('inspect')['debits'])==750
    finally:
        server.shutdown();thread.join();server.server_close();session.close()
    session=Session(directory,allowed_urls=[])
    try:
        assert session.call('settings')['values']['language']=='ru'
        assert sum(d['delta_mg'] for d in session.call('inspect')['debits'])==750
        assert session.call('desktop_snapshot')['runs'][key]['status']=='committed'
    finally:session.close()


def test_published_inventory_forms_lost_response_assignment_and_exact_edits(tmp_path):
    import copy
    from tracker_uid_runtime import AccountingOwner
    from test_uid_accounting import snapshot
    class Fleet:
        value={p:snapshot(p,{}) for p in ('a','b')}
        def snapshot(self):return copy.deepcopy(self.value)
    fleet=Fleet();owner=AccountingOwner(tmp_path/'ui.sqlite',fleet)
    owner.call('save_settings',values={'printers':[dict(id=p,name='Printer '+p,url='http://127.0.0.1:'+str(19840+i)) for i,p in enumerate(('a','b'))]},expected_revision=owner.call('settings')['revision'])
    server=serve(owner,fleet,app_info={'version':'2.0.0rc1','mode':'user'})
    thread=threading.Thread(target=server.serve_forever);thread.start();errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1050})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#nav-spools').click();page.locator('#inventory-create').click()
            page.locator('#new-name').fill('Precision PLA');page.locator('#new-mat').fill('PLA');page.locator('#new-weight').fill('125.259')
            lost=[]
            def lose_response(route):
                if not lost:
                    assert route.fetch().ok;lost.append(True);route.abort()
                else:route.continue_()
            page.route('**/api/desktop/spools/add',lose_response)
            with page.expect_event('requestfailed',predicate=lambda r:r.url.endswith('/spools/add')):
                page.locator('#t-add-btn').click()
            page.locator('#t-add-btn').click()
            page.wait_for_function("!document.getElementById('inventory-add-dialog').open")
            spools=owner.call('library_snapshot')['spools'];assert len(spools)==1
            sid=spools[0]['spool_id'];assert spools[0]['remaining_mg']==125259
            field=page.locator('#spools-table input[type=number]');assert field.input_value()=='125.259'
            field.fill('124.987')
            with page.expect_response('**/api/desktop/spools/update') as response:field.press('Tab')
            assert response.value.ok
            page.wait_for_function("document.querySelector('#spools-table input').value==='124.987'")
            assert owner.call('library_snapshot')['spools'][0]['remaining_mg']==124987
            page.get_by_role('button',name='Головки T0–T3',exact=True).click()
            page.locator('select[name=slot_1]').select_option(sid)
            with page.expect_response('**/api/desktop/slots') as response:page.locator('#slots-form button[type=submit]').click()
            assert response.value.ok
            page.wait_for_function("document.querySelector('.uid-inventory-assignments').textContent.includes('Printer a · T0')")
            page.get_by_role('button',name='Библиотека',exact=True).click()
            assert 'Printer a · T0' in page.locator('.uid-inventory-assignments').inner_text()
            page.locator('#nav-overview').click()
            assert '125' in page.locator('.head-remaining').first.inner_text()
            page.wait_for_function("document.getElementById('forecast-heading').textContent==='Прогноз нарезки'")
            page.screenshot(path='output/full-133-integration-ui/inventory-connected.png',full_page=True)
            page.reload();page.locator('#nav-spools').click()
            page.wait_for_function("document.querySelector('#spools-table input').value==='124.987'")
            assert len(owner.call('library_snapshot')['spools'])==1
            assert owner.call('inspect')['debits']==[]
            assert not errors,errors
            browser.close()
        package=owner.call('backup_package');checked=owner.call('validate_backup',package=package)
        owner.call('restore_backup',package=package,expected_revision=checked['current_revision'])
        assert owner.call('library_snapshot')['spools'][0]['remaining_mg']==124987
        assert owner.call('inspect')['debits']==[]
    finally:
        server.shutdown();thread.join();server.server_close();owner.close()


def test_two_printer_context_and_preupload_forecast_preserve_viewed_plate(bench,tmp_path):
    import os
    from dev.observer_fixture import payload
    from tracker_uid_forecast import SliceForecast
    from tracker_uid_runtime import AccountingOwner
    life,key,c=prepare(bench)
    fleet=bench[2]
    other=life.adapter.service.accounting.begin('b','Printer B job','1001',['1'],'test',fleet.snapshot())
    life.adapter.service.accounting.apply(other,1,{'1':1000},state='completed',source='test',basis='motion_estimate')
    copy=sqlite3.connect(tmp_path/'desktop.sqlite');c.db.backup(copy);copy.close()
    owner=AccountingOwner(tmp_path/'desktop.sqlite',fleet)
    owner.call('save_settings',values={'printers':[dict(id=p,name='Printer '+p,url='http://127.0.0.1:'+str(19860+i)) for i,p in enumerate(('a','b'))]},expected_revision=owner.call('settings')['revision'])
    for spool in owner.call('library_snapshot')['spools']:
        owner.call('update_spool',spool_id=spool['spool_id'],changes={'color':'#ff7f26' if spool['name']=='A' else '#2b9c70'},expected_revision=spool['revision'],request_id='color-'+spool['spool_id'],confirmed=True,note='Synthetic display fixture')
    for ch,name,color,grams in [('0','PLA Black','#151a1c','583.217'),('2','PLA Orange','#ff7f26','833.574'),('3','PLA White','#ffffff','195.82')]:
        owner.call('create_spool',name=name,remaining_g=grams,details={'color':color,'material':'PLA'},assignment=dict(printer_id='b',channel=ch,expected_version='',confirmed=True))
    root=tmp_path/'slices';metadata=root/'Test project'/'Metadata';metadata.mkdir(parents=True)
    first=metadata/'.42.0.gcode';second=metadata/'.42.1.gcode'
    first_source=str(first.relative_to(root));second_source=str(second.relative_to(root))
    first.write_bytes(payload('10, 0, 0, 0'));second.write_bytes(payload('0, 20, 0, 0'))
    os.utime(first,ns=(100000000000,100000000000));os.utime(second,ns=(200000000000,200000000000))
    forecast=SliceForecast(owner,root);forecast.poll();forecast.observer.settle=0;forecast.poll()
    server=serve(owner,fleet,forecast=forecast,app_info={'version':'2.0.0rc1','mode':'user'})
    thread=threading.Thread(target=server.serve_forever);thread.start();errors=[]
    before=owner.call('inspect')['debits']
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1050})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#uid-history-dialog[open]').wait_for();page.get_by_role('button',name='Закрыть',exact=True).click()
            page.locator('#forecast-plate').select_option(first_source)
            page.wait_for_function("document.getElementById('forecast-status').textContent.includes('По расчёту материала хватит')")
            page.locator('#desktop-forecast-details summary').click()
            assert 'Test project · .42.0.gcode' in page.locator('#desktop-forecast-source').inner_text()
            page.locator('#nav-spools').click()
            owner.call('save_settings',values={'safety_margin_g':7},expected_revision=owner.call('settings')['revision'])
            forecast.poll();page.evaluate('refreshSliceForecast(false)')
            assert page.locator('#view-spools').is_visible()
            assert page.locator('#forecast-plate').input_value()==first_source
            page.evaluate('loadData()')
            page.locator('#desktop-printer-picker').select_option('b')
            page.wait_for_function("desktopFormData.selected_printer==='b'")
            assert page.locator('#view-spools').is_visible()
            assert page.locator('#forecast-plate').input_value()==first_source
            assert owner.call('settings')['values']['selected_printer']=='b'
            page.locator('#nav-history').click()
            assert 'Printer B job' in page.locator('#view-history').inner_text()
            assert 'job.gcode' not in page.locator('#view-history').inner_text()
            page.locator('#nav-overview').click();page.locator('#forecast-plate').select_option(second_source)
            assert 'По расчёту материала хватит' in page.locator('#forecast-status').inner_text()
            assert '299' in page.locator('.head-remaining').nth(1).inner_text()
            # A late old reply/failure cannot overwrite a newer rendered result.
            for failure in (False,True):
                page.evaluate('''async failure=>{
                    const original=window.fetch;
                    const current=await (await original('/api/forecast')).json();
                    let release,count=0;
                    window.fetch=(url,options)=>{
                        if(url!=='/api/forecast')return original(url,options);
                        if(++count===1)return new Promise((resolve,reject)=>{
                            release=()=>failure?reject(Error('late failed response')):
                                resolve(new Response(JSON.stringify({...current,printer_id:'a',entries:[]})));
                        });
                        return Promise.resolve(new Response(JSON.stringify(current)));
                    };
                    try{const old=refreshSliceForecast(false);await refreshSliceForecast(false);release();await old}
                    finally{window.fetch=original}
                }''',failure)
                assert 'По расчёту материала хватит' in page.locator('#forecast-status').inner_text()
            page.screenshot(path='output/full-133-integration-ui/two-printers-forecast.png',full_page=True)
            # Simulate a failed observer request: no stale green assurance remains.
            page.route('**/api/desktop/forecast',lambda route:route.abort())
            page.evaluate('refreshSliceForecast(false)')
            assert 'По расчёту материала хватит' not in page.locator('#forecast-status').inner_text()
            assert page.locator('#desktop-forecast-source').inner_text()==''
            page.unroute('**/api/desktop/forecast');page.evaluate('refreshSliceForecast(false)')
            assert 'По расчёту материала хватит' in page.locator('#forecast-status').inner_text()
            # A .tmp result invalidates the last completed version before upload.
            Path(str(second)+'.tmp').write_bytes(payload('0, 500, 0, 0'));forecast.poll()
            page.evaluate('refreshSliceForecast(false)')
            assert '.42.1.gcode' not in page.locator('#desktop-forecast-source').inner_text()
            Path(str(second)+'.tmp').replace(second);forecast.poll();forecast.poll()
            page.evaluate('refreshSliceForecast(false)')
            assert 'Материала не хватает' in page.locator('#forecast-status').inner_text()
            assert not errors,errors
            assert owner.call('inspect')['debits']==before
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();owner.close()
    owner=AccountingOwner(tmp_path/'desktop.sqlite',fleet)
    try:
        assert owner.call('settings')['values']['selected_printer']=='b'
        assert owner.call('inspect')['debits']==before
    finally:owner.close()
