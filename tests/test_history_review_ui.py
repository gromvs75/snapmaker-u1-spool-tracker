import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from test_legacy_backup_restore import old_backup,restore
from tracker_uid_session import Session
from tracker_uid_gui import serve


def test_history_review_layout_reopen_and_edited_amount_once(tmp_path,old_backup):
    s=Session(tmp_path/'profile',allowed_urls=[]);restore(s,old_backup)
    s.call('save_settings',values={'language':'ru'},expected_revision=s.call('settings')['revision'])
    data=s.call('desktop_snapshot');key=next(k for k,v in data['saved_history'].items() if v['filename']=='saved-2.gcode')
    server=serve(s,s.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
    screens=Path('output/history-review-ui');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#uid-history-dialog[open]').wait_for()
            page.locator('.uid-history-heading button').click()
            page.screenshot(path=str(screens/'review-list.png'),full_page=True)
            for lang in ('ru','en','de','uk','es'):
                page.locator('#lang-picker').select_option(lang)
                page.wait_for_function('(v)=>currentLang===v',arg=lang)
                page.locator('.uid-review-row').filter(has_text='saved-2.gcode').locator('button').click()
                page.locator('#uid-history-dialog[open]').wait_for()
                for width in (1202,700):
                    page.set_viewport_size(dict(width=width,height=950))
                    buttons=page.locator('#uid-history-dialog .uid-history-actions button')
                    boxes=[buttons.nth(i).bounding_box() for i in range(buttons.count())]
                    assert len(boxes)==3
                    for i,a in enumerate(boxes):
                        for b in boxes[i+1:]:
                            assert (a['x']+a['width']+9<=b['x'] or b['x']+b['width']+9<=a['x'] or a['y']+a['height']+9<=b['y'] or b['y']+b['height']+9<=a['y']),(lang,width,a,b)
                    assert page.locator('#uid-history-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.set_viewport_size(dict(width=1202,height=950))
                if lang=='ru':page.screenshot(path=str(screens/'review-dialog.png'),full_page=True)
                page.locator('.uid-history-heading button').click()
            page.locator('#lang-picker').select_option('ru')
            page.locator('.uid-review-row').filter(has_text='saved-2.gcode').locator('button').click()
            page.get_by_role('button',name='Закрыть без списания',exact=True).click()
            page.locator('#uid-history-dialog input[type=checkbox]').check()
            page.get_by_role('button',name='Закрыть без списания',exact=True).click()
            page.wait_for_function("!document.getElementById('uid-history-dialog').open")
            assert s.call('history_detail',job_key=key)['accounted_mg']==0
            page.locator('#nav-history').click()
            row=page.locator('.history-row').filter(has_text='saved-2.gcode')
            assert 'Закрыто без списания' in row.inner_text()
            row.locator('.uid-expand').click()
            page.locator('#uid-history-dialog[open]').wait_for()
            assert 'Закрыто без дополнительного списания' in page.locator('.uid-history-state').inner_text()
            page.locator('#uid-history-edit').click()
            field=page.locator('.uid-extra-amount');assert field.input_value()==''
            field.fill('3.5');page.locator('#uid-review-note').fill('Проверены катушка и расход после закрытия');page.locator('#uid-review-ack').check()
            page.screenshot(path=str(screens/'manual-edit.png'),full_page=True)
            lost=[]
            def lose_response(route):
                if not lost:assert route.fetch().ok;lost.append(True);route.abort()
                else:route.continue_()
            page.route('**/api/history_decide',lose_response);page.on('dialog',lambda d:d.accept())
            with page.expect_event('requestfailed',predicate=lambda r:r.url.endswith('/history_decide')):page.locator('#uid-review-apply').click()
            page.locator('#uid-review-apply').click()
            page.wait_for_function("!document.getElementById('uid-history-dialog').open")
            assert s.call('history_detail',job_key=key)['accounted_mg']==3500
            page.locator('.history-row').filter(has_text='saved-2.gcode').locator('.uid-expand').click()
            page.locator('#uid-history-dialog[open]').wait_for()
            assert page.locator('#uid-history-edit').count()==0
            assert 'учёт уже завершён' in page.locator('#uid-history-dialog').inner_text()
            assert not errors
            browser.close()
        saved=s.call('backup_package');restore(s,saved)
        assert s.call('history_detail',job_key=key)['accounted_mg']==3500
        assert not s.call('history_detail',job_key=key)['can_review']
    finally:server.shutdown();thread.join();server.server_close();s.close()
    s=Session(tmp_path/'profile',allowed_urls=[])
    try:assert s.call('history_detail',job_key=key)['accounted_mg']==3500
    finally:s.close()
