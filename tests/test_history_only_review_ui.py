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
            dialog=page.locator('#uid-history-dialog')
            spool=page.locator('#uid-history-spool')
            amount=dialog.get_by_label('Расход, г',exact=True).first
            apply=page.locator('#uid-review-apply')
            expect(spool).to_have_value('')
            expect(amount).to_be_visible()
            expect(amount).to_be_disabled()
            expect(apply).to_be_disabled()
            expect(dialog.locator('.uid-saved-plan')).to_have_count(0)
            assert not app.call('inspect')['debits'] and not value['writes']
            if not lost_reply:
                page.screenshot(path=str(out/'manual-empty.png'))
            spool.select_option('other')
            expect(amount).to_be_enabled()
            expect(apply).to_have_text('Учесть в Tracker')
            amount.fill('9')
            spool.select_option(sid)
            expect(amount).to_have_value('')
            expect(apply).to_have_text('Учесть в Tracker и продолжить')
            amount.fill('3.5')
            expect(apply).to_be_disabled()
            page.locator('#uid-review-ack').check()
            for invalid in ('0','500.001'):
                amount.fill(invalid)
                expect(apply).to_be_disabled()
            amount.fill('3.5')
            expect(apply).to_be_enabled()
            if lost_reply:
                dialog.get_by_role('button',name='Добавить ещё катушку').click()
                second=dialog.locator('.uid-manual-spools select').nth(1)
                expect(second).to_have_value('')
                expect(second.locator('option',has_text='Test PLA')).to_have_attribute('disabled','')
                expect(apply).to_be_disabled()
                dialog.get_by_role('button',name='Убрать строку').click()
                expect(apply).to_be_enabled()
                dialog.get_by_role('button',name='Добавить ещё катушку').click()
                second.select_option('other')
                dialog.get_by_label('Расход, г',exact=True).nth(1).fill('1.25')
                expect(apply).to_be_enabled()
            debit_count=2 if lost_reply else 1
            accounted_mg=4750 if lost_reply else 3500
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
            assert len(app.call('inspect')['debits'])==debit_count and not value['writes']
            page.locator('#uid-history-send').click()
            expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman')
            assert len(value['writes'])==1 and value['balance']==496.5
            key=app.call('inspect')['debits'][0]['job_key']
            for _ in range(3):
                app.call('observe_history',pid,[job]);app.call('history',pid,[job])
            page.locator('#uid-history-delivery-refresh').click()
            assert len(value['writes'])==1 and len(app.call('inspect')['debits'])==debit_count
            page.screenshot(path=str(out/('sent-'+str(lost_reply)+'.png')))
            page.locator('#uid-history-dialog .gd-close').click();page.locator('#nav-history').click()
            expect(page.locator('.history-row')).to_have_count(1)
            expect(page.locator('.history-row')).to_contain_text('Учтено в Tracker')
            assert not errors
            browser.close()
        package=app.call('backup_package');restore(app,package)
        detail=app.call('history_detail',job_key=key)
        assert detail['accounted_mg']==accounted_mg
        assert {debit['spool_id']:debit['delta_mg'] for debit in detail['debits']}==(
            {sid:3500,'other':1250} if lost_reply else {sid:3500})
        assert not app.call('history_detail',job_key=key)['can_review']
    finally:
        server.shutdown();server.server_close();thread.join();app.close()
    app=Session(tmp_path/'profile',allowed_urls=[])
    try:
        assert app.call('history_detail',job_key=key)['accounted_mg']==accounted_mg
        assert len(app.call('desktop_snapshot')['runs'])==1
    finally:app.close()


def test_history_only_local_spool_has_amount_before_confirmation(tmp_path):
    old=Store(tmp_path/'old')

    def seed(data):
        data['language']='ru'
        data['spools']={'generic':dict(name='Generic Basis',material='PLA',remaining_g=445.7)}

    old.update(seed)
    app=Session(tmp_path/'profile')
    restore(app,create_backup(old,'1.3.3'))
    pid=app.call('settings')['values']['selected_printer']
    job=dict(job_id='local-only',start_time=2000.,filename='local-only.gcode',status='completed')
    app.call('observe_history',pid,[job])
    server=serve(app,app.fleet)
    thread=threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            page=browser.new_page(viewport=dict(width=1202,height=950))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            page.locator('#nav-history').click()
            row=page.locator('.history-row').filter(has_text='local-only.gcode')
            row.locator('.uid-expand').click()
            page.locator('#uid-history-prepare').click()

            dialog=page.locator('#uid-history-dialog')
            dialog.locator('#uid-history-spool').select_option('generic',timeout=7000)
            page.locator('#uid-review-ack').check()
            amount=dialog.get_by_label('Расход, г',exact=True)
            apply=dialog.get_by_role('button',name='Учесть в Tracker',exact=True)
            expect(amount).to_be_enabled()
            expect(amount).to_have_value('')
            expect(apply).to_be_disabled()
            expect(page.locator('#uid-history-add-spool')).to_be_hidden()
            assert not app.call('inspect')['debits']
            out=Path('output/resumed-print-ui')
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/'manual-local-selected.png'))

            amount.fill('15')
            expect(apply).to_be_enabled()
            apply.click()
            expect(dialog).to_be_hidden()
            expect(row).to_contain_text('Учтено')
            app.call('observe_history',pid,[job])
            app.call('history',pid,[job])
            debit,=app.call('inspect')['debits']
            assert (debit['spool_id'],debit['delta_mg'])==('generic',15000)
            assert app.call('library_snapshot')['spools'][0]['remaining_mg']==430700
            assert not app.call('delivery_list')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()
