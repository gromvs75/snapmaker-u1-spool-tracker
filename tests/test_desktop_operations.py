from desktop_ui_helpers import accept_graphite_confirmations, audit_dialog
import threading
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet
from test_accounting import setup_plan
from test_uid_motion_adapter import evidence


def test_full_shell_interrupted_unlock_and_confirmed_transfer(tmp_path):
    app=Session(tmp_path/'app',fleet_factory=Fleet,allowed_urls=['http://127.0.0.1:19101','http://127.0.0.1:19102'])
    app.call('save_settings',values=dict(printers=[dict(id=p,name=p,url='http://127.0.0.1:'+str(19101+i)) for i,p in enumerate(('a','b'))],selected_printer='a'),expected_revision=app.call('settings')['revision'])
    app.call('connect_printers',confirmed=True)
    sid=app.call('create_spool','Manual source',100,details={'material':'PLA'},assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))['spool_id']
    store,*_=setup_plan(tmp_path/'gcode');e=evidence(store);e['start']=app.call('inventory_snapshot','a')
    app.call('start','a',filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
    app.call('disconnected','a','Test sleep')
    server=serve(app,app.fleet,status_reader=lambda _: 'standby',app_info={'mode':'user','version':'2.0.0rc2'});thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();page.on('dialog',lambda d:d.accept());accept_graphite_confirmations(page);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('#uid-history-dialog[open]').wait_for();page.get_by_role('button',name='Закрыть',exact=True).click()
            page.locator('#nav-history').click();page.locator('.desktop-unlock').click()
            assert page.locator('#desktop-unlock-apply').is_disabled()
            audit_dialog(page,'unlock')
            page.locator('#desktop-unlock-stopped').check();page.locator('#desktop-unlock-gap').check()
            with page.expect_response('**/api/resolve') as r:page.locator('#desktop-unlock-apply').click()
            assert r.value.ok and r.value.json()['deadline'] is not None
            page.locator('#desktop-operation-dialog').wait_for(state='hidden')
            state=app.call('inspect');assert state['jobs'][0]['state']=='resolved' and not state['manual_assignments'][0]['confirmed']
            page.locator('#nav-spools').click();page.locator('.graphite-actions-open').first.click();page.locator('#graphite-spool-actions [data-action=transfer]').click()
            assert page.locator('#desktop-operation-dialog .gs-route').is_visible()
            assert page.locator('#desktop-operation-dialog .gs-field').count()==2
            assert page.locator('#desktop-operation-dialog .gs-footer #desktop-transfer-apply').is_visible()
            page.screenshot(path='output/graphite-ui/transfer.png',full_page=True)
            page.locator('#desktop-transfer-printer').select_option('b');page.locator('#desktop-transfer-head').select_option('1')
            with page.expect_response('**/api/transfer') as r:page.locator('#desktop-transfer-apply').click()
            assert r.value.ok
            page.locator('#desktop-operation-dialog').wait_for(state='hidden')
            state=app.call('inspect');a=state['manual_assignments'][0]
            assert (a['printer_id'],a['channel'],a['confirmed'])==('b','1',1)
            assert state['jobs'][0]['unlock']['completed'] and not state['debits']
            assert state['spools'][0]['remaining_mg']==100000 and not errors
            browser.close()
    finally:server.shutdown();thread.join();server.server_close();app.close()
