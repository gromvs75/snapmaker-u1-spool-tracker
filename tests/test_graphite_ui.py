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
    legacy.update(seed)
    app=Session(tmp_path/'profile',allowed_urls=[])
    package=create_backup(legacy,'1.3.3');preview=app.call('validate_backup',package=package)
    app.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
    remote_state,url=remote
    sender=Sender(app,[url])
    server=serve(app,app.fleet,sender=sender,app_info={'mode':'user','version':'2.0.0rc9'})
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
            for width in [1280,1024,800]:
                page.set_viewport_size({'width':width,'height':1000})
                for nav in ['overview','spools','history','settings']:
                    page.locator('#nav-'+nav).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,nav)
            page.set_viewport_size({'width':1280,'height':1000})
            page.locator('#nav-spools').click();page.screenshot(path=str(out/'library.png'),full_page=True)
            page.locator('#inventory-create').click();page.screenshot(path=str(out/'add-spool.png'),full_page=True)
            page.locator('#inventory-add-dialog .dialog-close').click()
            page.locator('.inventory-param-button').first.click();page.screenshot(path=str(out/'parameters.png'),full_page=True)
            page.locator('#inventory-param-dialog .dialog-close').click()
            page.locator('#desktop-tags-open').click();page.screenshot(path=str(out/'uid.png'),full_page=True)
            page.locator('#desktop-tags-close').click()
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click();page.screenshot(path=str(out/'printer.png'),full_page=True)
            assert not errors,errors
            assert not app.connected and not remote_state['writes']
            browser.close()
    finally:
        server.shutdown();thread.join();server.server_close();app.close()
