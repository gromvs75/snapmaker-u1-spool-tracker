"""One-shot probe feedback is visible and does not start collectors."""
import threading
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet


def test_probe_progress_success_failure_and_stale_target(tmp_path,monkeypatch):
    gate=threading.Event();calls=[];fail=False
    class Probe:
        def __init__(self,url):calls.append(url)
        def status(self):
            assert gate.wait(10)
            if fail:raise OSError('Synthetic connection refused')
            return {'print_stats':{'state':'standby'}}
        def read(self,path):return {'objects':[]}
    monkeypatch.setattr('tracker_uid_collectors.ReadOnlyMoonraker',Probe)
    app=Session(tmp_path/'profile',fleet_factory=Fleet,allowed_urls=['http://127.0.0.1:19101'])
    app.call('save_settings',values={'printers':[dict(id='a',name='A',url='http://127.0.0.1:19101')]},expected_revision=app.call('settings')['revision'])
    server=serve(app,app.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            page.locator('#printer-test').click()
            assert page.locator('#printer-test-result').get_attribute('data-state')=='pending'
            assert page.locator('#printer-test-result').is_visible()
            assert page.locator('#printer-test').is_disabled()
            gate.set();page.wait_for_function("document.getElementById('printer-test-result').dataset.state==='ok'")
            assert 'Moonraker отвечает' in page.locator('#printer-test-result').inner_text()
            page.evaluate('loadData()')
            assert 'Moonraker отвечает' in page.locator('#printer-test-result').inner_text()
            assert not app.connected and not app.call('inspect')['debits']
            for language in ['de','uk','es','en','ru']:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(v)=>currentLang===v',arg=language)
                with page.expect_response('**/api/test_printer'):page.locator('#printer-test').click()
                assert page.locator('#printer-test-result').get_attribute('data-state')=='ok'
            fail=True
            with page.expect_response('**/api/test_printer'):page.locator('#printer-test').click()
            assert page.locator('#printer-test-result').get_attribute('data-state')=='error'
            assert 'Synthetic connection refused' in page.locator('#printer-test-result').inner_text()
            fail=False;gate.clear();page.locator('#printer-test').click()
            page.locator('#printer-host').fill('127.0.0.2');gate.set()
            page.wait_for_function('!document.getElementById("printer-test").disabled')
            assert page.locator('#printer-test-result').inner_text()==''
            assert all(url=='http://127.0.0.1:19101' for url in calls)
            assert not app.connected and not app.call('inspect')['debits']
            browser.close()
    finally:gate.set();server.shutdown();thread.join();server.server_close();app.close()
