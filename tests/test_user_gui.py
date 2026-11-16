import json
import sqlite3
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from test_uid_motion_adapter import bench
from test_uid_recovery import prepare
from test_uid_settings_backup import Fleet
from tracker_uid_history_review import HistoryReview
from tracker_uid_gui import serve
from tracker_uid_session import Session
from tracker_uid_forecast import SliceForecast
from dev.observer_fixture import payload


def test_user_shell_offline_plan_manual_confirmation_and_screens(bench,tmp_path):
    life,key,c=prepare(bench);HistoryReview(life.adapter.service.accounting)
    folder=tmp_path/'user';folder.mkdir()
    target=sqlite3.connect(folder/'tracker.sqlite');c.db.backup(target);target.close()
    session=Session(folder,fleet_factory=Fleet,allowed_urls=[])
    session.call('save_settings',values={'printers':[dict(id=p,name='Мастерская '+p.upper(),url=f'http://127.0.0.1:{19000+i}') for i,p in enumerate(('a','b'))]},expected_revision=session.call('settings')['revision'])
    for i,(name,color,weight) in enumerate([('Prusament Galaxy Black','#44495c',742.367),('Bambu PETG Orange','#ff8a35',123.456),('Polymaker PLA Teal','#48b9b3',576.135)]):
        session.call('create_spool',name=name,remaining_g=str(weight),details={'material':'PLA','color':color})
    slices=folder/'slices'/'Sample'/'Metadata';slices.mkdir(parents=True);(slices/'.42.0.gcode').write_bytes(payload('25.1234, 10.5678, 0, 0'))
    forecast=SliceForecast(session,folder/'slices');forecast.poll();forecast.observer.settle=0;forecast.poll()
    server=serve(session,session.fleet,app_info={'mode':'user','version':'2.0.0rc1','commit':'fixture','isolation':'Искусственные данные'},forecast=forecast)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    screenshots=Path('output/user-candidate-ui');screenshots.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1202,'height':950});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.wait_for_selector('#desktop-printer-picker option',state='attached')
            page.locator('#uid-history-dialog[open]').wait_for()
            page.get_by_role('button',name='Закрыть',exact=True).click()
            assert page.locator('#lang-picker option').count()==5
            page.locator('#nav-overview').click()
            page.get_by_text('Прогноз после нарезки',exact=True).wait_for()
            page.wait_for_function("document.getElementById('forecast-status').textContent.includes('?')")
            assert page.locator('#forecast-status').evaluate('(e)=>getComputedStyle(e).color')=='rgb(148, 163, 184)'
            assert 'Уже учтено: 0' in page.locator('#review-content').inner_text()
            page.screenshot(path=str(screenshots/'overview.png'),full_page=True)
            page.locator('#nav-spools').click()
            assert page.locator('.inventory-tabs button').all_text_contents()==['Библиотека','Головки T0–T3']
            assert page.locator('#spools-table input[type=number]').count()>=3
            page.screenshot(path=str(screenshots/'spools.png'),full_page=True)
            page.locator('#nav-settings').click()
            assert page.locator('.settings-nav button').all_text_contents()==['Принтер','Spoolman','Учёт','Резервная копия']
            page.screenshot(path=str(screenshots/'settings.png'),full_page=True)
            page.locator('#nav-history').click();page.get_by_role('button',name='Раскрыть задание',exact=True).click()
            assert '1 г' in page.locator('.uid-saved-plan').inner_text()
            page.screenshot(path=str(screenshots/'history.png'),full_page=True)
            page.get_by_role('button',name='Да — проверить списание',exact=True).click()
            page.locator('.uid-extra-amount').fill('0.750');page.locator('#uid-review-note').fill('Проверена фактически завершённая печать');page.locator('#uid-review-ack').check()
            page.locator('#uid-review-apply').click();page.locator('#uid-history-dialog').wait_for(state='hidden')
            assert sum(d['delta_mg'] for d in session.call('inspect')['debits'])==750
            page.locator('#nav-overview').click()
            assert 'Подтверждено вручную' in page.locator('#latest-accounting').inner_text()
            assert '0,8' in page.locator('#latest-accounting').inner_text()
            page.locator('#latest-accounting').get_by_role('button',name='Раскрыть задание').click()
            page.locator('#uid-history-dialog[open]').wait_for()
            assert '0,8' in page.locator('.uid-saved-plan').inner_text()
            page.get_by_role('button',name='Закрыть',exact=True).click()
            assert not errors,errors
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':700,'height':900})
            for selector in ['#nav-overview','#nav-spools','#nav-history','#nav-settings']:
                page.locator(selector).click()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),selector
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();session.close()
