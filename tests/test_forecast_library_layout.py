import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_forecast import SliceForecast
from backup import create_backup
from storage import Store
from dev.observer_fixture import payload


def test_imported_forecast_and_library_fit_all_languages(tmp_path):
    old=Store(tmp_path/'old-synthetic')
    def seed(db):
        db.update(language='ru',safety_margin_g=10)
        db['printer'].update(host='127.0.0.1',port=19991,enabled=True)
        for i,(name,color,weight) in enumerate([('Generic Basis','#151a1c',571.597),('Generic Basic','#ffffff',195.82),('Generic','#ff7f26',833.574),('Generic PLA','#2b9c70',886.58)]):
            sid=str(i);db['spools'][sid]=dict(name=name,material='PLA',remaining_g=weight,color=color);db['slots'][str(i+1)]=sid
    old.update(seed)
    s=Session(tmp_path/'profile',allowed_urls=[])
    package=create_backup(old,'1.3.3');preview=s.call('validate_backup',package=package)
    s.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    folder=tmp_path/'slices'/'Test project'/'Metadata';folder.mkdir(parents=True)
    (folder/'.42.3.gcode').write_bytes(payload('4.01, 0, 0, 0'))
    forecast=SliceForecast(s,tmp_path/'slices');forecast.poll();forecast.observer.settle=0;forecast.poll()
    server=serve(s,s.fleet,forecast=forecast);thread=threading.Thread(target=server.serve_forever);thread.start()
    screens=Path('output/native-forecast-library');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950))
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.wait_for_function("document.getElementById('forecast-status').textContent.includes('По расчёту материала хватит')")
            assert 'Пластина 4' in page.locator('#forecast-single').inner_text()
            assert '567,6' in page.locator('.forecast-head-note').inner_text()
            page.locator('#desktop-forecast-details summary').click()
            assert 'сохранённым катушкам' in page.locator('#desktop-forecast-provisional').inner_text()
            page.locator('#desktop-forecast-details summary').click()
            page.screenshot(path=str(screens/'forecast.png'),full_page=True)
            page.locator('#nav-spools').click()
            page.locator('#spools-table .graphite-balance').first.wait_for()
            for lang in ('ru','en','de','uk','es'):
                page.locator('#lang-picker').select_option(lang)
                page.wait_for_function('(lang)=>currentLang===lang',arg=lang)
                for width in (1202,1000,700):
                    page.set_viewport_size(dict(width=width,height=950))
                    metrics=page.locator('#view-spools .table-scroll').evaluate('(e)=>({w:e.clientWidth,sw:e.scrollWidth,h:e.clientHeight,sh:e.scrollHeight})')
                    assert metrics['sw']<=metrics['w']+1,(lang,width,metrics)
                    assert metrics['sh']<=metrics['h']+1,(lang,width,metrics)
                page.set_viewport_size(dict(width=1202,height=950))
                if lang=='ru':page.screenshot(path=str(screens/'library.png'),full_page=True)
            assert not errors
            browser.close()
        assert not s.connected and s.call('inspect')['debits']==[]
    finally:server.shutdown();thread.join();server.server_close();s.close()
