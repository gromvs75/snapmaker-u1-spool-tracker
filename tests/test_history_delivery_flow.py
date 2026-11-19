"""Single-window manual review and direct Spoolman delivery, with lost replies."""
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright,expect
from backup import create_backup
from storage import Store
from spoolman_bridge import remote_id,blank
from tracker_uid_session import Session
from tracker_uid_sender import Sender
from tracker_uid_gui import serve
from test_legacy_backup_restore import restore
from test_desktop_services import remote
from desktop_ui_helpers import audit_dialog


@pytest.mark.parametrize('fault',['','drop_after','lost_browser_reply'])
def test_history_review_to_delivery_stays_in_one_dialog(tmp_path,remote,fault):
    value,url=remote;sid=remote_id(url,42);old=Store(tmp_path/'old')
    def seed(data):
        data['language']='ru';data['spoolman']=dict(blank(),url=url,mode='send',epoch='synthetic')
        data['spools']={sid:dict(name='Test PLA',material='PLA',remaining_g=500,spoolman=dict(url=url,id=42))}
        data['slots']['1']=sid
        data['plans']['one']=dict(filename='review.gcode',sha256='a'*64,size=100,weights=[12,0,0,0],spool_ids=[sid,'','',''],created_at=1000,status='review',printer=dict(data['printer']))
        data['runs']['one']=dict(job_id='one',plan_id='one',start_time=2000,status='review',filename='review.gcode',physical_weights=[12,0,0,0],physical_spool_ids=[sid,'','',''],tool_mapping=[0,1,2,3])
    old.update(seed);app=Session(tmp_path/'profile',allowed_urls=[url]);restore(app,create_backup(old,'1.3.3'))
    app.call('save_settings',values=dict(spoolman_mode='send'),expected_revision=app.call('settings')['revision'])
    sender=Sender(app,[url]);server=serve(app,app.fleet,sender=sender);thread=threading.Thread(target=server.serve_forever);thread.start()
    out=Path('output/history-delivery');out.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1202,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#uid-history-dialog[open]').wait_for();page.locator('#uid-history-edit').click()
            expect(page.locator('.uid-extra-amount')).to_have_value('12');expect(page.locator('#uid-review-note')).to_have_value('')
            expect(page.locator('#uid-history-dialog')).to_contain_text('Отредактируйте при необходимости')
            page.locator('.uid-extra-amount').fill('3.5');page.locator('#uid-review-ack').check();audit_dialog(page,'history-prefill');page.screenshot(path=str(out/'step-1.png'))
            assert value['writes']==[]
            page.locator('#uid-review-apply').click();expect(page.locator('#uid-history-send')).to_be_visible()
            assert app.call('inspect')['debits'][0]['delta_mg']==3500 and value['writes']==[]
            expect(page.locator('#uid-history-delivery-rows')).to_contain_text('500 g → после списания 496,5 g')
            audit_dialog(page,'history-spoolman');page.screenshot(path=str(out/'step-2.png'))
            lost=[]
            if fault=='lost_browser_reply':
                def lose(route):
                    if not lost:assert route.fetch().ok;lost.append(True);route.abort()
                    else:route.continue_()
                page.route('**/api/delivery_confirm_send',lose)
            else:value['fault']=fault
            page.locator('#uid-history-send').click()
            if fault=='lost_browser_reply':
                expect(page.locator('#uid-history-error')).to_be_visible();page.locator('#uid-history-send').click()
            if fault=='drop_after':
                expect(page.locator('#uid-history-dialog')).to_contain_text('Результат прошлой отправки неизвестен')
                assert app.call('delivery_list')[0]['state']=='uncertain';assert page.locator('#uid-history-send').count()==0
            else:
                expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman')
                assert app.call('delivery_list')[0]['state']=='sent'
            assert len(value['writes'])==1 and value['balance']==496.5
            page.locator('#uid-history-delivery-refresh').click();expect(page.locator('#uid-history-delivery-rows')).to_be_visible()
            assert len(value['writes'])==1 and len(app.call('inspect')['debits'])==1
            page.screenshot(path=str(out/('result-'+(fault or 'sent')+'.png')))
            page.locator('#uid-history-dialog .gd-close').click();page.locator('#nav-history').click()
            expect(page.locator('.history-row')).to_contain_text('Учтено в Tracker')
            expect(page.locator('.history-row')).to_contain_text('нужна сверка' if fault=='drop_after' else 'отправлено')
            assert not errors
            browser.close()
    finally:server.shutdown();server.server_close();thread.join();app.close()
