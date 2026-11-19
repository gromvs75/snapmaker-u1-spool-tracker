"""Browser -> real local HTTP -> owner SQLite -> synthetic Spoolman transport."""
from functools import partial
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright, expect
from desktop_ui_helpers import audit_dialog
from test_rfid_enrollment import enrollment, decoded, URL
from tracker_rfid import RfidWorker
from tracker_uid_gui import serve
from tracker_uid_sender import Sender


def test_new_and_second_tag_browser_flow(enrollment,monkeypatch):
    svc,o,f,s,_=enrollment;f.set(decoded('creality'))
    import tracker_rfid_enrollment
    monkeypatch.setattr(tracker_rfid_enrollment,'RfidWorker',partial(RfidWorker,client_factory=s))
    server=serve(o,f,status_reader=lambda pid:'standby',sender=Sender(o,[URL]))
    thread=threading.Thread(target=server.serve_forever);thread.start()
    out=Path('output/rfid-ui');out.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#desktop-tags-open').click()
            expect(page.locator('#desktop-rfid-metadata')).to_contain_text('Creality · PLA · #0000FF')
            expect(page.locator('#desktop-tag-mass')).to_have_value('')
            expect(page.locator('#desktop-tag-next')).to_be_disabled()
            page.locator('#desktop-tag-mass').fill('840.123');page.locator('#desktop-rfid-density').fill('1.24')
            for field,value in [('diameter','1.75'),('nominal','1000')]:
                control=page.locator('#desktop-rfid-'+field)
                if not control.input_value():control.fill(value)
            audit_dialog(page,'rfid-new');page.screenshot(path=str(out/'new.png'))
            assert not s.posts
            page.locator('#desktop-tag-next').click()
            expect(page.locator('#desktop-tag-save')).to_be_disabled()
            page.locator('#desktop-tag-ack').check();page.screenshot(path=str(out/'confirm.png'))
            page.locator('#desktop-tag-save').click()
            expect(page.locator('#desktop-tags-message')).to_contain_text('Готово')
            assert len(s.rows['spool'])==1 and s.rows['spool'][0]['remaining_weight']==840.123
            sid=o.call('library_snapshot')['spools'][0]['spool_id'];s.rows['spool'][0]['remaining_weight']=623.5
            worker=RfidWorker(o,[URL],client_factory=s,interactive=True);worker.scan('a','0')
            f.set(decoded('creality',1));page.locator('#desktop-tags-refresh').click()
            expect(page.locator('#desktop-tag-mode')).to_have_value('existing')
            expect(page.locator('#desktop-tag-existing')).to_contain_text('Spoolman #1')
            page.screenshot(path=str(out/'second-tag.png'));page.locator('#desktop-tag-next').click()
            expect(page.locator('#desktop-tag-attachment')).to_contain_text('623,5')
            expect(page.locator('#desktop-tag-attachment')).to_contain_text('не сбрасывается')
            page.locator('#desktop-tag-ack').check();page.locator('#desktop-tag-save').click()
            expect(page.locator('#desktop-tags-message')).to_contain_text('Готово')
            assert len(s.rows['spool'])==1 and not s.puts
            for side in (0,1):
                f.set(decoded('creality',side));row=worker.scan('a','0');assert row['spool_id']==sid and row['remaining_mg']==623500
            # Stale selection cannot create a second physical spool.
            f.set(decoded('tigertag'));page.locator('#desktop-tags-refresh').click()
            expect(page.locator('#desktop-rfid-metadata')).to_contain_text('Bambu Lab · PLA')
            page.locator('#desktop-tag-mass').fill('500');page.locator('#desktop-rfid-density').fill('1.24')
            page.locator('#desktop-tag-next').click();page.locator('#desktop-tag-ack').check();f.set(decoded('tigertag',1));page.locator('#desktop-tag-save').click()
            expect(page.locator('#desktop-tags-message')).not_to_have_text('')
            assert len(s.rows['spool'])==1 and not errors
            browser.close()
    finally:server.shutdown();server.server_close();thread.join()
