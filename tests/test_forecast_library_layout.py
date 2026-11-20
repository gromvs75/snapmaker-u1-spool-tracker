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
    (folder/'.42.3.gcode').write_bytes(payload('15.08, 2.36').replace(
        b'; printer_model', b'; filament_colour = #FD8008;#000000\n; filament_type = PLA;PLA\n; printer_model'))
    (folder/'model_settings.config').write_text('<config><plate><metadata key="plater_id" value="2"/><metadata key="gcode_file" value="Metadata/.42.3.gcode"/></plate></config>')
    forecast=SliceForecast(s,tmp_path/'slices');forecast.poll();forecast.observer.settle=0;forecast.poll()
    server=serve(s,s.fleet,forecast=forecast);thread=threading.Thread(target=server.serve_forever);thread.start()
    screens=Path('output/native-forecast-library');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950))
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.wait_for_function("document.getElementById('forecast-status').textContent.includes('По прогнозу хватает с резервом')")
            assert 'Стол 2' in page.locator('#forecast-single').inner_text()
            materials = page.locator('#desktop-forecast-materials > span')
            assert materials.all_text_contents() == ['Материал 1 · 15,08 гр. → T2', 'Материал 2 · 2,36 гр. → T0']
            colors = page.locator('.forecast-material-color')
            assert [colors.nth(i).get_attribute('title') for i in range(2)] == ['#FD8008', '#000000']
            previews = page.locator('#sidebar-slots .sidebar-slot')
            assert '2,36' in previews.nth(0).locator('.dash-head-forecast').inner_text()
            assert '15,08' in previews.nth(2).locator('.dash-head-forecast').inner_text()
            assert previews.nth(1).locator('.dash-head-forecast').count() == 0
            assert previews.nth(3).locator('.dash-head-forecast').count() == 0
            orange = next(spool for spool in s.call('library_snapshot')['spools'] if spool['name'] == 'Generic')
            s.call('update_spool', spool_id=orange['spool_id'], changes={'remaining_g':15},
                   expected_revision=orange['revision'], request_id='low-orange', confirmed=True, note='Synthetic test')
            forecast.poll();page.evaluate('refreshSliceForecast(false)')
            page.wait_for_function("document.getElementById('forecast-status').textContent.includes('материала не хватает')")
            assert 'Не хватает с резервом' in previews.nth(2).locator('.dash-head-forecast').inner_text()
            page.screenshot(path=str(screens/'forecast.png'),full_page=True)
            page.locator('#nav-spools').click()
            page.locator('#spools-table .graphite-balance').first.wait_for()
            for lang in ('ru','en','de','uk','es'):
                page.locator('#lang-picker').select_option(lang)
                page.wait_for_function('(lang)=>currentLang===lang',arg=lang)
                expected={'ru':'Стол 2','en':'Plate 2','de':'Platte 2','uk':'Стіл 2','es':'Placa 2'}[lang]
                page.wait_for_function('(s)=>document.getElementById("forecast-single").textContent===s',arg=expected)
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
