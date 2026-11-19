"""Real loopback HTTP collectors, without UID/motion/history availability."""
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright
from tracker_uid_session import Session
from tracker_uid_collectors import create_workers
from tracker_uid_gui import serve


@contextmanager
def printer(state, filename):
    value = dict(state=state, filename=filename, offline=False, requests=[])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            value['requests'].append(self.path)
            if value['offline']:
                self.send_error(503); return
            if self.path.startswith('/printer/objects/query?'):
                result = dict(status=dict(print_stats=dict(state=value['state'], filename=value['filename'], **value.get('stats',{})), toolhead=dict(extruder=value.get('extruder','extruder3')), **value.get('extra',{})))
            elif self.path == '/printer/objects/list':
                result = dict(objects=['print_stats', 'toolhead'])
            else:
                self.send_error(404); return
            raw = json.dumps(dict(result=result)).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try: yield value, f'http://127.0.0.1:{server.server_port}'
    finally: server.shutdown(); thread.join(); server.server_close()


def wait(fn):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        if fn(): return
        time.sleep(.05)
    raise AssertionError('Monitor did not reach expected state')


def test_two_printers_status_survives_missing_uid_motion_and_history(tmp_path):
    with printer('printing', 'a.gcode') as (a, url_a), printer('paused', 'b.gcode') as (b, url_b):
        s = Session(tmp_path, allowed_urls=[url_a, url_b], worker_factory=create_workers)
        def select(pid):
            s.call('save_settings', values={'selected_printer':pid}, expected_revision=s.call('settings')['revision'])
        def monitor(): return s.call('desktop_snapshot')['monitor']
        try:
            s.call('save_settings', values={'printers':[dict(id='a', name='A', url=url_a), dict(id='b', name='B', url=url_b)]}, expected_revision=s.call('settings')['revision'])
            assert monitor()['state'] == 'disabled'
            assert s.call('test_printer', url=url_a) == dict(state='printing', uid_available=False)
            s.call('connect_printers', confirmed=True)
            wait(lambda: monitor()['state'] == 'printing')
            assert monitor()['filename'] == 'a.gcode' and monitor()['active_head'] == 3
            assert s.fleet.snapshot()['a']['state'] != 'ready'
            s.call('disconnected', 'a', 'Motion lost')
            assert monitor()['state'] == 'printing'
            select('b'); wait(lambda: monitor()['state'] == 'paused')
            assert monitor()['filename'] == 'b.gcode'
            a['offline'] = True
            select('a'); wait(lambda: not monitor()['connected'])
            assert monitor()['state'] == 'disconnected' and not monitor()['filename']
            select('b'); assert monitor()['state'] == 'paused'
            a.update(offline=False, state='complete')
            select('a'); wait(lambda: monitor()['state'] == 'complete')
            s.call('disconnect_printers', confirmed=True)
            assert monitor()['state'] == 'disabled' and not monitor()['filename']
            a['state'] = 'printing'
            s.call('connect_printers', confirmed=True); wait(lambda: monitor()['state'] == 'printing')
            # Repeat current status/history errors cannot create local/remote debits.
            assert not s.call('inspect')['debits'] and not s.call('delivery_list')
            assert a['requests'].count('/printer/objects/query?print_stats&toolhead&display_status&virtual_sdcard') >= 3
        finally: s.close()
        s = Session(tmp_path, allowed_urls=[])
        try: assert s.call('desktop_snapshot')['monitor']['state'] == 'disabled'
        finally: s.close()


def test_stale_telemetry_cannot_claim_printing(tmp_path, monkeypatch):
    from test_desktop_services import Fleet
    s = Session(tmp_path, fleet_factory=Fleet, allowed_urls=['http://127.0.0.1:19999'])
    try:
        s.call('save_settings', values={'printers':[dict(id='a',name='A',url='http://127.0.0.1:19999')]}, expected_revision=s.call('settings')['revision'])
        s.call('connect_printers', confirmed=True)
        with monkeypatch.context() as patch:
            patch.setattr('tracker_uid_guard.time.time', lambda: 1)
            s.call('monitor_status','a',dict(print_stats=dict(state='printing',filename='old.gcode')))
        m=s.call('desktop_snapshot')['monitor']
        assert not m['connected'] and m['state']=='disconnected'
    finally: s.close()


def test_live_ui_and_add_printer_placement_all_languages(tmp_path):
    with printer('printing', 'Assembly_PLA_2h21m.gcode') as (value, url):
        s=Session(tmp_path,allowed_urls=[url],worker_factory=create_workers)
        s.call('save_settings',values={'language':'ru','printers':[dict(id='a',name='U1 · simulator',url=url)]},expected_revision=s.call('settings')['revision'])
        s.call('connect_printers',confirmed=True)
        server=serve(s,s.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
        screens=Path('output/printer-monitor-ui');screens.mkdir(parents=True,exist_ok=True)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1202,height=950));errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
                for lang, text in [('ru','Печать идёт'),('en','Printing'),('de','Druck läuft'),('uk','Друк триває'),('es','Imprimiendo')]:
                    page.locator('#lang-picker').select_option(lang)
                    page.wait_for_function('(text)=>document.getElementById("overview-connection").textContent===text',arg=text)
                    assert page.locator('#overview-file').inner_text()=='Assembly_PLA_2h21m.gcode'
                    assert page.locator('#desktop-printer-context #desktop-printer-add').count()==1
                    assert page.locator('#printer-form #desktop-printer-add').count()==0
                    assert page.locator('#desktop-printer-add').is_disabled()
                    for width in (1202,700):
                        page.set_viewport_size(dict(width=width,height=950))
                        assert page.locator('#desktop-printer-context').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                    page.set_viewport_size(dict(width=1202,height=950))
                page.locator('#lang-picker').select_option('ru')
                page.screenshot(path=str(screens/'printing.png'),full_page=True)
                value['state']='paused'
                page.wait_for_function('document.getElementById("overview-connection").textContent==="Пауза"')
                value['offline']=True
                page.wait_for_function('document.getElementById("overview-connection").textContent==="Нет связи с принтером"')
                value.update(offline=False,state='complete')
                page.wait_for_function('document.getElementById("overview-connection").textContent==="Печать завершена"')
                s.call('disconnect_printers',confirmed=True)
                page.reload();page.locator('#desktop-printer-add').click()
                assert page.locator('#printer-form').is_visible()
                assert page.locator('#desktop-printer-name').input_value()==''
                assert page.locator('#printer-host').input_value()==''
                page.screenshot(path=str(screens/'add-printer.png'),full_page=True)
                assert not errors
                browser.close()
        finally: server.shutdown();thread.join();server.server_close();s.close()
