"""Approved grouping preserves warnings, details, plate selection and pause actions."""
import json
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_forecast import SliceForecast
from backup import create_backup
from storage import Store
from dev.observer_fixture import payload
from test_desktop_services import Fleet


def test_grouped_overview_all_languages_and_guard_actions(tmp_path):
    old=Store(tmp_path/'synthetic-133')
    def seed(db):
        db.update(language='ru',safety_margin_g=10)
        db['printer'].update(host='127.0.0.1',port=19991,enabled=True)
        for i,(name,color,weight) in enumerate([('Generic Basis','#151a1c',571.597),('Generic Basic','#ffffff',195.82),('Generic','#ff7f26',833.574),('Generic PLA','#2b9c70',886.58)]):
            sid=str(i);db['spools'][sid]=dict(name=name,material='PLA',remaining_g=weight,color=color);db['slots'][str(i+1)]=sid
    old.update(seed)
    s=Session(tmp_path/'profile',fleet_factory=Fleet,allowed_urls=['http://127.0.0.1:19991'])
    package=create_backup(old,'1.3.3');v=s.call('validate_backup',package=package);s.call('restore_backup',package=package,expected_revision=v['current_revision'],confirmed=True)
    pid=s.call('settings')['values']['printers'][0]['id']
    s.call('save_settings',values={'guard_modes':{pid:'strict'}},expected_revision=s.call('settings')['revision'])
    s.call('connect_printers',confirmed=True);s.call('guard_arm',pid)
    job=dict(job_id='grouped',start_time=time.time(),filename='Assembly_PLA_2h21m.gcode',status='in_progress')
    ticket=s.call('guard_check',pid,job,dict(file_sha256='a'*64,logical_weights=[0,0,0,54.7],mapping=[0,1,2,3]))
    s.call('guard_result',pid,ticket['attempt'],'warning')
    live={'state':'printing','filename':job['filename']};stop=threading.Event()
    def telemetry():
        while not stop.is_set():s.owner.call('monitor_status',pid,dict(print_stats=dict(live)));stop.wait(.2)
    tele=threading.Thread(target=telemetry);tele.start()
    folder=tmp_path/'slices'/'Project'/'Metadata';folder.mkdir(parents=True)
    (folder/'.42.0.gcode').write_bytes(payload('0, 0, 0, 54.7'))
    (folder/'.42.1.gcode').write_bytes(payload('4.01, 0, 0, 0'))
    forecast=SliceForecast(s,tmp_path/'slices');forecast.poll();forecast.observer.settle=0;forecast.poll()
    server=serve(s,s.fleet,forecast=forecast);thread=threading.Thread(target=server.serve_forever);thread.start()
    screens=Path('output/grouped-overview-ui');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#desktop-check-details summary').wait_for()
            page.wait_for_function('document.getElementById("forecast-plate").options.length===2')
            for lang in ('ru','en','de','uk','es'):
                page.locator('#lang-picker').select_option(lang);page.wait_for_function('(l)=>currentLang===l',arg=lang)
                assert page.locator('.overview-card').inner_text().count(job['filename'])==1
                assert 'assignment/balance unconfirmed' not in page.locator('#guard-content').inner_text()
                for width in (1202,700):
                    page.set_viewport_size(dict(width=width,height=950))
                    for selector in ('.overview-card','#slice-forecast'):
                        assert page.locator(selector).evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.locator('#desktop-check-details summary').click()
                assert page.locator('#desktop-check-details table').is_visible()
                page.locator('#desktop-forecast-details summary').click()
                assert page.locator('#desktop-forecast-source').is_visible()
                assert page.locator('#forecast-hide').is_visible()
                # Live polls must not collapse disclosures or move the selected plate.
                options=page.locator('#forecast-plate option').evaluate_all('(xs)=>xs.map(x=>x.value)')
                page.locator('#forecast-plate').select_option(options[0]);page.wait_for_timeout(700)
                assert page.locator('#forecast-plate').input_value()==options[0]
                assert page.locator('#desktop-check-details').get_attribute('open') is not None
                assert page.locator('#desktop-forecast-details').get_attribute('open') is not None
                page.locator('#desktop-check-details summary').click();page.locator('#desktop-forecast-details summary').click()
            page.set_viewport_size(dict(width=1202,height=950));page.locator('#lang-picker').select_option('ru')
            page.screenshot(path=str(screens/'overview.png'),full_page=True)
            page.locator('#desktop-check-details summary').click();page.locator('#desktop-forecast-details summary').click()
            page.screenshot(path=str(screens/'details.png'),full_page=True)
            live['state']='paused';s.call('guard_result',pid,ticket['attempt'],'paused')
            page.locator('#guard-content .form-inline button').first.wait_for()
            assert page.locator('#guard-content .form-inline button').count()==2
            requests=[]
            def action(route):requests.append(route.request.post_data_json);route.fulfill(json={})
            page.route('**/api/desktop/guard/decision',action)
            page.locator('#guard-content .form-inline button').last.click()
            with page.expect_response('**/api/desktop/guard/decision'):
                page.locator('#graphite-confirm-apply').click()
            page.wait_for_function('!fullLoadInFlight')
            assert requests and requests[0]['action']=='resume'
            live['state']='complete'
            page.wait_for_function("document.querySelector('#view-overview #guard-content').children.length===0")
            page.locator('#nav-history').click()
            page.locator('#history-start-checks #desktop-past-check > summary').click()
            if page.locator('#desktop-check-details').get_attribute('open') is None:
                page.locator('#desktop-check-details > summary').click()
            assert page.locator('#history-start-checks table').is_visible()
            page.screenshot(path=str(screens/'historical-start-check.png'),full_page=True)
            assert not errors
            browser.close()
        assert not s.call('inspect')['debits'] and not s.call('delivery_list')
    finally:stop.set();tele.join();server.shutdown();thread.join();server.server_close();s.close()
