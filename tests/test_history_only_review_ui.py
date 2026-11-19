"""History-only recovery through the real HTTP UI and a loopback Spoolman."""
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from backup import create_backup
from storage import Store
from spoolman_bridge import blank, remote_id
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_sender import Sender
from test_desktop_services import remote
from test_legacy_backup_restore import restore
from desktop_ui_helpers import audit_dialog


@pytest.mark.parametrize('lost_reply',[False,True])
def test_history_only_choose_spool_send_restore_and_replay(tmp_path,remote,lost_reply):
    value,url=remote;sid=remote_id(url,42);old=Store(tmp_path/'old')
    def seed(data):
        data['language']='ru';data['spoolman']=dict(blank(),url=url,mode='send',epoch='synthetic')
        data['spools']={sid:dict(name='Test PLA',material='PLA',remaining_g=500,spoolman=dict(url=url,id=42)),
                        'other':dict(name='Other roll',material='PLA',remaining_g=200)}
    old.update(seed)
    app=Session(tmp_path/'profile',allowed_urls=[url]);restore(app,create_backup(old,'1.3.3'))
    app.call('save_settings',values=dict(spoolman_mode='send'),expected_revision=app.call('settings')['revision'])
    pid=app.call('settings')['values']['selected_printer']
    job=dict(job_id='tangle-resumed',start_time=2000.,filename='tangle.gcode',status='error')
    app.call('observe_history',pid,[job]);job['status']='completed';app.call('observe_history',pid,[job])
    sender=Sender(app,[url]);server=serve(app,app.fleet,sender=sender)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    out=Path('output/resumed-print-ui');out.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#nav-history').click()
            row=page.locator('.history-row').filter(has_text='tangle.gcode');row.locator('.uid-expand').click()
            expect(page.locator('#uid-history-prepare')).to_be_visible()
            page.locator('#uid-history-prepare').click()
            expect(page.locator('#uid-history-spool')).to_have_value('')
            assert page.locator('.uid-extra-amount').count()==0
            assert not app.call('inspect')['debits'] and not value['writes']
            page.locator('#uid-history-spool').select_option(sid);page.locator('#uid-history-add-spool').click()
            expect(page.locator('.uid-extra-amount')).to_have_value('')
            page.locator('.uid-extra-amount').fill('3.5');page.locator('#uid-review-ack').check()
            audit_dialog(page,'history-only-manual')
            page.screenshot(path=str(out/('manual-'+str(lost_reply)+'.png')))
            lost=[]
            if lost_reply:
                def lose(route):
                    if not lost:assert route.fetch().ok;lost.append(True);route.abort()
                    else:route.continue_()
                page.route('**/api/history_decide',lose)
            page.locator('#uid-review-apply').click()
            if lost_reply:
                expect(page.locator('#uid-history-error')).to_be_visible();page.locator('#uid-review-apply').click()
            expect(page.locator('#uid-history-send')).to_be_visible()
            assert len(app.call('inspect')['debits'])==1 and not value['writes']
            page.locator('#uid-history-send').click()
            expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman')
            assert len(value['writes'])==1 and value['balance']==496.5
            key=app.call('inspect')['debits'][0]['job_key']
            for _ in range(3):
                app.call('observe_history',pid,[job]);app.call('history',pid,[job])
            page.locator('#uid-history-delivery-refresh').click()
            assert len(value['writes'])==1 and len(app.call('inspect')['debits'])==1
            page.screenshot(path=str(out/('sent-'+str(lost_reply)+'.png')))
            page.locator('#uid-history-dialog .gd-close').click();page.locator('#nav-history').click()
            expect(page.locator('.history-row')).to_have_count(1)
            expect(page.locator('.history-row')).to_contain_text('Учтено в Tracker')
            assert not errors
            browser.close()
        package=app.call('backup_package');restore(app,package)
        assert app.call('history_detail',job_key=key)['accounted_mg']==3500
        assert not app.call('history_detail',job_key=key)['can_review']
    finally:
        server.shutdown();server.server_close();thread.join();app.close()
    app=Session(tmp_path/'profile',allowed_urls=[])
    try:
        assert app.call('history_detail',job_key=key)['accounted_mg']==3500
        assert len(app.call('desktop_snapshot')['runs'])==1
    finally:app.close()
