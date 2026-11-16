"""Presentation regression against real adapters and a temporary SQLite store."""
import json
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright
from storage import Store
from backup import create_backup
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_sender import Sender
from test_desktop_services import remote


def test_graphite_full_shell_colors_order_languages_and_responsive_forms(tmp_path, remote):
    legacy=Store(tmp_path/'legacy')
    def seed(d):
        d['language']='ru'
        d['printer'].update(host='127.0.0.1',port=19991,enabled=False)
        for i,(name,color,mass) in enumerate([('Generic Basis','#151a1c',571.597),('Generic Basic','#ffffff',195.82),('Generic Orange','#ff7f26',833.574),('Generic PLA','#2b9c70',886.58)]):
            d['spools'][str(i)]=dict(name=name,color=color,material='PLA',remaining_g=mass)
            d['slots'][str(i+1)]=str(i)
        for i,grams in enumerate([11.62,34.46,9.125]):
            pid='plan-'+str(i)
            filename=['plate_PLA_19m53s.gcode','Korper3_PLA_1h2m.gcode','shell_PLA_7h27m.gcode'][i]
            d['plans'][pid]=dict(filename=filename,sha256=str(i)*64,size=10,weights=[grams,0,0,0],spool_ids=['0','','',''],created_at=1000+i,status='committed',printer=dict(d['printer']))
            d['runs']['run-'+str(i)]=dict(job_id='history-'+str(i),plan_id=pid,start_time=2000+i,status='committed',filename=filename,physical_weights=[grams,0,0,0],physical_spool_ids=['0','','',''],tool_mapping=[0,1,2,3])
    legacy.update(seed)
    app=Session(tmp_path/'profile',allowed_urls=[])
    package=create_backup(legacy,'1.3.3');preview=app.call('validate_backup',package=package)
    app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    remote_state,url=remote
    sender=Sender(app,[url])
    server=serve(app,app.fleet,sender=sender,app_info={'mode':'user','version':'2.0.0rc11'})
    thread=threading.Thread(target=server.serve_forever);thread.start()
    out=Path('output/graphite-ui');out.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.wait_for_function('desktopFormData?.spools && Object.keys(desktopFormData.spools).length===4')
            assert page.locator('body.graphite').count()==1
            assert page.evaluate('document.querySelector(".sidebar").getBoundingClientRect().bottom<=document.querySelector("#slice-forecast").getBoundingClientRect().top')
            assert page.locator('.graphite-head-art').count()==4
            for language in ['ru','en','de','uk','es']:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(l)=>currentLang===l',arg=language)
                assert page.locator('.graphite-head-art').count()==4
            page.locator('#lang-picker').select_option('ru')
            page.screenshot(path=str(out/'overview.png'),full_page=True)
            page.locator('#nav-settings').click();page.locator('[data-settings-section=spoolman]').click();page.locator('[data-sm-tab=connection]').click()
            page.locator('#sm-url').fill(url);page.locator('#sm-read').check();page.locator('#sm-save').click()
            page.locator('[data-sm-tab=spools]').click();page.locator('#sm-refresh-selected').click()
            page.locator('.sm-spool-row').wait_for()
            assert page.locator('.sm-spool-row .sm-art').count()==1
            assert page.locator('.graphite-material').inner_text()=='PLA'
            assert '#ff7f26' in page.locator('.sm-spool-row .sm-art').inner_html().lower()
            page.locator('.sm-spool-row').click()
            assert page.locator('#sm-assign').is_enabled()
            page.screenshot(path=str(out/'spoolman.png'),full_page=True)
            for width in [1280,945,800]:
                page.set_viewport_size({'width':width,'height':1000})
                for nav in ['overview','spools','history','settings']:
                    page.locator('#nav-'+nav).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,nav)
            # Same client width as the approved reference, not a wider test-only page.
            page.set_viewport_size({'width':945,'height':800})
            for language in ['en','de','uk','es','ru']:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(l)=>currentLang===l',arg=language)
                boxes=[page.locator(q).bounding_box() for q in ['.graphite-brand','.top-nav','#lang-picker']]
                assert max(b['y']+b['height']/2 for b in boxes)-min(b['y']+b['height']/2 for b in boxes)<2
                assert boxes[0]['x']+boxes[0]['width']<boxes[1]['x']
                assert boxes[1]['x']+boxes[1]['width']<boxes[2]['x']
            page.locator('#nav-spools').click()
            assert page.locator('.spool-inventory thead th').count()==5
            assert page.locator('.graphite-balance').first.inner_text()=='571,6 гр.'
            assert page.locator('#spools-table input').first.input_value()=='571.597'
            for row in page.locator('#spools-table tr').all():
                assert row.bounding_box()['height']<85
                assert row.locator('.graphite-assignments').is_visible()
                assert not row.locator('.delete-spool').is_visible()
            assert page.locator('.inventory-tabs button').first.bounding_box()['height']<45
            page.locator('.graphite-actions-open').first.click()
            assert page.locator('#graphite-spool-actions [data-action=delete]').is_visible()
            page.keyboard.press('Escape')
            assert not page.locator('.delete-spool').first.is_visible()
            page.screenshot(path=str(out/'library.png'),full_page=True)
            page.locator('#nav-history').click()
            assert page.locator('.history-row').count()==3
            assert '9,1' in page.locator('.history-usage').first.inner_text()
            assert page.locator('.graphite-history-job .history-date').count()==3
            page.screenshot(path=str(out/'history.png'),full_page=True)
            page.locator('#nav-spools').click()
            page.locator('#inventory-create').click();page.screenshot(path=str(out/'add-spool.png'),full_page=True)
            page.locator('#inventory-add-dialog .dialog-close').click()
            page.locator('.inventory-param-button').first.click();page.screenshot(path=str(out/'parameters.png'),full_page=True)
            assert page.locator('#inventory-param-dialog .gs-field').count()==2
            assert page.locator('#inventory-param-dialog .gs-footer #cal-save').is_visible()
            page.locator('#inventory-param-dialog .gs-edit-color').click()
            assert page.locator('dialog[open]').count()==1
            assert page.locator('.gs-swatch').count()==34
            page.screenshot(path=str(out/'color.png'),full_page=True)
            boxes=page.locator('.gs-swatch').evaluate_all('(xs)=>xs.map(x=>{const r=x.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})')
            assert all(b['w']==28 and b['h']==28 for b in boxes)
            assert len({b['y'] for b in boxes})==5
            original=app.call('library_snapshot')['spools']
            page.locator('.gs-swatch[data-color="#ff7f26"]').click()
            assert app.call('library_snapshot')['spools']==original
            page.keyboard.press('Escape')
            assert app.call('library_snapshot')['spools']==original
            # Check all open dialogs, not just the underlying page, on every language.
            for language in ['ru','en','de','uk','es']:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(l)=>currentLang===l',arg=language)
                page.locator('.graphite-actions-open').first.click()
                assert page.locator('#graphite-spool-actions .gs-action').count()>=4
                if language=='ru':page.screenshot(path=str(out/'actions.png'),full_page=True)
                page.locator('#graphite-spool-actions [data-action=params]').click()
                for width in [945,480]:
                    page.set_viewport_size({'width':width,'height':800})
                    assert page.locator('#inventory-param-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                    assert page.locator('#cal-save').bounding_box()['width']>100
                page.locator('#inventory-param-dialog .gs-edit-color').click()
                assert page.locator('#graphite-color-dialog').evaluate('(e)=>e.scrollHeight<=e.clientHeight+1 && e.scrollWidth<=e.clientWidth+1')
                page.keyboard.press('Escape');page.set_viewport_size({'width':945,'height':800})
            page.locator('#lang-picker').select_option('ru')
            page.locator('.inventory-param-button').first.click();page.locator('.gs-edit-color').click()
            page.locator('.gs-swatch[data-color="#ff7f26"]').click()
            # Lost response must allow the same safe request, without changing balances.
            lost=[]
            def lose_color_reply(route):
                if not lost:
                    assert route.fetch().ok;lost.append(True);route.abort()
                else:route.continue_()
            page.route('**/api/desktop/spools/color',lose_color_reply)
            with page.expect_event('requestfailed',predicate=lambda r:r.url.endswith('/spools/color')):
                page.locator('#graphite-color-save').click()
            assert page.locator('#graphite-color-dialog').is_visible()
            with page.expect_response('**/api/desktop/spools/color') as response:
                page.locator('#graphite-color-save').click()
            assert response.value.ok
            page.locator('#graphite-color-dialog').wait_for(state='hidden')
            assert [s['remaining_mg'] for s in app.call('library_snapshot')['spools']]==[s['remaining_mg'] for s in original]
            assert page.locator('.inventory-name .sm-art').count()==4

            page.locator('#desktop-tags-open').click();page.screenshot(path=str(out/'uid.png'),full_page=True)
            page.locator('#desktop-tags-close').click()
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click();page.screenshot(path=str(out/'printer.png'),full_page=True)
            # Main navigation stays reachable when long content is scrolled.
            page.set_viewport_size({'width':945,'height':430})
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            assert page.locator('.graphite-chrome').bounding_box()['y']==0
            page.locator('#nav-history').click()
            assert not errors,errors
            assert not app.connected and not remote_state['writes']
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();app.close()
