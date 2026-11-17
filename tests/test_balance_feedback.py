"""Balance conflicts refresh the dialog, never retry an obsolete write."""
import threading
import uuid
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet


def exercise_balance(page, change_elsewhere, screenshot=None):
    page.locator('#nav-spools').click()
    page.locator('.graphite-actions-open').first.click()
    page.locator('#graphite-spool-actions [data-action=balance]').click()
    page.locator('#graphite-balance-dialog[open]').wait_for()
    page.locator('#graphite-balance-value').fill('80.01')
    page.locator('#graphite-balance-ack').check()
    change_elsewhere()
    with page.expect_response('**/api/desktop/spools/update') as response:
        page.locator('#graphite-balance-save').click()
    assert response.value.status == 409
    page.wait_for_function("document.getElementById('graphite-balance-result').textContent.includes('не сохранено')")
    assert page.locator('#graphite-balance-value').input_value() == '80.01'
    assert not page.locator('#graphite-balance-ack').is_checked()
    assert page.locator('#graphite-balance-save').is_disabled()
    assert '90' in page.locator('.gs-current-balance').inner_text()
    assert not page.locator('#graphite-confirm-dialog[open]').count()
    if screenshot:page.screenshot(path=str(screenshot),full_page=True)
    page.locator('#graphite-balance-ack').check()
    with page.expect_response('**/api/desktop/spools/update') as response:
        page.locator('#graphite-balance-save').click()
    assert response.value.ok
    page.locator('#graphite-balance-dialog').wait_for(state='hidden')
    assert '80' in page.locator('#graphite-balance-saved').inner_text()


def test_balance_conflict_refresh_and_saved_start_check(tmp_path):
    app=Session(tmp_path/'profile',fleet_factory=Fleet,allowed_urls=[])
    sid=app.call('create_spool','Synthetic PLA',100)['spool_id']
    server=serve(app,app.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();alerts=[]
            page.on('dialog',lambda d:(alerts.append(d.message),d.accept()))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            def change():
                # Independent writer command changes the same spool while form is open.
                spool=next(s for s in app.call('library_snapshot')['spools'] if s['spool_id']==sid)
                app.call('update_spool',spool_id=sid,changes={'remaining_g':'90'},expected_revision=spool['revision'],request_id=uuid.uuid4().hex,confirmed=True,note='Synthetic concurrent edit')
            exercise_balance(page,change)
            assert not alerts
            assert app.call('library_snapshot')['spools'][0]['remaining_mg']==80010
            page.locator('.graphite-actions-open').first.click()
            page.locator('#graphite-spool-actions [data-action=balance]').click()
            page.locator('#graphite-balance-dialog[open]').wait_for()
            page.locator('#graphite-balance-value').fill('70.01');page.locator('#graphite-balance-ack').check()
            requests=[]
            def lose_response(route):
                requests.append(route.request.post_data_json);route.fetch();route.abort()
            page.route('**/api/desktop/spools/update',lose_response)
            page.locator('#graphite-balance-save').click()
            page.wait_for_function("document.getElementById('graphite-balance-result').textContent.includes('Ответ не получен')")
            assert app.call('library_snapshot')['spools'][0]['remaining_mg']==70010
            assert not page.locator('#graphite-balance-ack').is_checked()
            page.unroute('**/api/desktop/spools/update',lose_response)
            page.locator('#graphite-balance-ack').check()
            with page.expect_response('**/api/desktop/spools/update') as retry:
                page.locator('#graphite-balance-save').click()
            assert retry.value.json()['status']=='duplicate'
            assert retry.value.request.post_data_json['_request_id']==requests[0]['_request_id']
            page.locator('#graphite-balance-dialog').wait_for(state='hidden')
            assert not app.call('inspect')['debits']
            page.locator('#nav-overview').click()
            page.evaluate("""() => {window.savedCheck={last_guard:{state:'warning',filename:'old.gcode',rows:[{tool:'T3',status:'unassigned',required_g:54.7,remaining_g:886.58}],time:'2026-11-16T14:00:28Z'},monitor:{connected:true,state:'complete',filename:'old.gcode'}};renderGuard(savedCheck,true)}""")
            assert page.locator('#view-history #desktop-past-check').count()==1
            assert not page.locator('#view-overview .desktop-check').count()
            assert not page.locator('#desktop-past-check').get_attribute('open')
            assert not page.locator('#guard-content table').is_visible()
            page.evaluate("savedCheck.monitor.state='printing';renderGuard(savedCheck,true)")
            assert not page.locator('#desktop-past-check').count()
            assert page.locator('#guard-content .desktop-check').is_visible()
            assert page.evaluate('savedCheck.last_guard.rows[0].remaining_g')==886.58
            browser.close()
    finally:server.shutdown();thread.join();server.server_close();app.close()
