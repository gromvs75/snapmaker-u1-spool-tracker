"""A late full-screen refresh must not undo a completed connection action."""
import threading
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet


def test_late_refresh_cannot_restore_connected_controls(tmp_path):
    app=Session(tmp_path/'profile',allowed_urls=['http://127.0.0.1:19101'],fleet_factory=Fleet)
    app.call('save_settings',values=dict(language='ru',printers=[dict(id='a',name='Bench',url='http://127.0.0.1:19101')],selected_printer='a'),expected_revision=app.call('settings')['revision'])
    app.call('connect_printers',confirmed=True)
    server=serve(app,app.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.wait_for_function('desktopFormData?.connections?.connected')
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            held=[]
            def delay_first(route):
                if not held:
                    response=route.fetch();held.append((route,response));page.evaluate('window.delayedRefreshHeld=true')
                else:route.continue_()
            page.route('**/api/desktop/data',delay_first)
            page.evaluate('()=>{window.delayedRefresh=loadData()}')
            page.wait_for_function('window.delayedRefreshHeld')
            assert held
            with page.expect_response('**/api/connections_stop') as response:page.locator('#desktop-connections-toggle').click()
            assert response.value.ok and not app.connected
            page.wait_for_function('!desktopFormData.connections.connected')
            route,response=held[0];route.fulfill(response=response)
            page.evaluate('window.delayedRefresh')
            assert page.evaluate('desktopFormData.connections.connected') is False
            assert page.evaluate('desktopLatestData.connections.connected') is False
            assert 'Подключить' in page.locator('#desktop-connections-toggle').inner_text()
            browser.close()
    finally:server.shutdown();server.server_close();thread.join();app.close()
