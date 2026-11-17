"""Real presentation confirmations must preserve cancellation and stale guards."""
import threading
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet
from desktop_ui_helpers import audit_dialog


def test_custom_confirmation_cancel_stale_assignment_and_language(tmp_path):
    app=Session(tmp_path/'profile',fleet_factory=Fleet,allowed_urls=['http://127.0.0.1:19101'])
    app.call('save_settings',values={'printers':[dict(id='a',name='Workshop',url='http://127.0.0.1:19101')]},expected_revision=app.call('settings')['revision'])
    app.call('connect_printers',confirmed=True)
    sid=app.call('create_spool','PLA Green',100,details={'color':'#2b9c70'})['spool_id']
    server=serve(app,app.fleet,app_info={'version':'2.0.0rc12','mode':'user'})
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#nav-spools').click();page.locator('[data-inventory-tab=slots]').click()
            page.locator('select[name=slot_1]').select_option(sid)
            page.locator('#t-save-slots').click();page.locator('#graphite-confirm-dialog[open]').wait_for()
            audit_dialog(page,'assignment-confirm')
            assert not app.call('inspect')['manual_assignments']
            page.locator('#graphite-confirm-cancel').click()
            assert not app.call('inspect')['manual_assignments']
            page.locator('#t-save-slots').click();page.locator('#graphite-confirm-dialog[open]').wait_for()
            # Inventory changes while awaiting confirmation. Never silently rebase.
            app.call('create_spool','Added elsewhere',200)
            with page.expect_response('**/api/desktop/slots') as response:page.locator('#graphite-confirm-apply').click()
            assert response.value.status==409
            assert not app.call('inspect')['manual_assignments'] and not app.call('inspect')['debits']
            page.evaluate('loadData()');page.wait_for_function('Object.keys(desktopFormData.spools).length===2')
            page.locator('select[name=slot_1]').select_option(sid);page.locator('#t-save-slots').click()
            with page.expect_response('**/api/desktop/slots') as response:page.locator('#graphite-confirm-apply').click()
            assert response.value.ok
            assert len(app.call('inspect')['manual_assignments'])==1 and not app.call('inspect')['debits']
            for language in ['de','uk','es','en','ru']:
                page.locator('#lang-picker').click()
                page.locator(f'#graphite-language-dialog input[value={language}]').check()
                audit_dialog(page,'language-'+language)
                page.locator('#graphite-language-save').click()
                page.wait_for_function('(l)=>currentLang===l',arg=language)
                assert app.call('settings')['values']['language']==language
            app.call('disconnect_printers',confirmed=True)
            page.evaluate('loadData()');page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            page.locator('#desktop-connections-toggle').click();page.locator('#graphite-confirm-dialog[open]').wait_for()
            settings=app.call('settings');app.call('save_settings',values={'safety_margin_g':17},expected_revision=settings['revision'])
            page.evaluate('loadData()')
            with page.expect_response('**/api/connections_start') as response:page.locator('#graphite-confirm-apply').click()
            assert response.value.status==409 and not app.connected
            assert not errors,errors
            browser.close()
    finally:server.shutdown();thread.join();server.server_close();app.close()
