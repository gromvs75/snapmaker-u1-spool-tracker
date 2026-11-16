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
            for language,overview,forecast_title in [('en','Overview','Slice forecast'),('de','Übersicht','Prognose nach dem Slicen'),('uk','Огляд','Slice forecast'),('es','Resumen','Slice forecast'),('ru','Обзор','Прогноз после нарезки')]:
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
            page.wait_for_function("document.getElementById('forecast-heading').textContent==='Прогноз после нарезки'")
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
