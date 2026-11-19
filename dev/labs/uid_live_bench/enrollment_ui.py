"""Real browser driving the ordinary local GUI against an isolated owner."""
from contextlib import contextmanager
import threading
from playwright.sync_api import sync_playwright, expect
from tracker_uid_gui import serve
from tracker_uid_sender import Sender


@contextmanager
def browser_enrollment(owner,fleet,url,output):
    server=serve(owner,fleet,status_reader=lambda pid:fleet.snapshot()[pid]['print_state'],sender=Sender(owner,[url]))
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
            yield BrowserEnrollment(page,output)
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close();thread.join()


class BrowserEnrollment:
    def __init__(self,page,output):self.page=page;self.output=output
    def apply(self,kind,uid,*,sid=None,remaining=1000):
        page=self.page
        if not page.locator('#desktop-tags-dialog').is_visible():page.locator('#desktop-tags-open').click()
        else:page.locator('#desktop-tags-refresh').click()
        expect(page.locator('#desktop-rfid-metadata')).to_contain_text(kind.upper())
        expect(page.locator('#desktop-tag-next')).to_be_visible()
        page.locator('#desktop-tag-mode').select_option('existing' if sid else 'new')
        if sid:page.locator('#desktop-tag-existing').select_option(sid)
        else:
            page.locator('#desktop-tag-mass').fill(str(remaining))
            for field,value in [('density','1.24'),('diameter','1.75'),('nominal','1000')]:
                control=page.locator('#desktop-rfid-'+field)
                if not control.input_value():control.fill(value)
        page.locator('#desktop-tag-next').click()
        expect(page.locator('#desktop-tag-attachment')).to_contain_text(uid)
        page.screenshot(path=str(self.output/(kind+('-pair' if sid else '-new')+'.png')))
        page.locator('#desktop-tag-ack').check();page.locator('#desktop-tag-save').click()
        expect(page.locator('#desktop-tags-message')).to_contain_text('Готово',timeout=15000)
