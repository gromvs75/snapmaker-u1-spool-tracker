"""Packaged app + actual WebView2 UI + loopback synthetic reader/Spoolman."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'tests')]
from test_rfid_enrollment import decoded
from test_rfid_bambu import Server
from test_rfid_roll_identity import tag as shared_instance_tag
from dev.labs.uid_candidate_bench.run import wait,native_windows
from dev.labs.uid_live_bench.enrollment_ui import BrowserEnrollment
from playwright.sync_api import sync_playwright,expect
from tracker_app import VERSION


def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=True)
    profile=Path(tempfile.mkdtemp(prefix='rfid-packaged-'))/'profile';sm=Server();checks=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def call(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length']))) if self.headers.get('Content-Length') else None
            path=self.path.removeprefix('/api/v1');result,_=sm.request(self.command,path,data)
            raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        do_GET=do_POST=do_PUT=call
    remote=ThreadingHTTPServer(('127.0.0.1',0),Handler);remote_thread=threading.Thread(target=remote.serve_forever);remote_thread.start()
    smurl=f'http://127.0.0.1:{remote.server_port}';printer=f'http://127.0.0.1:{port()}';cdp=port();app=None;sim=None;descriptor={}
    log=(out/'process.log').open('w',encoding='utf-8')
    def request(url,body=None,headers=None):
        with urlopen(Request(url,data=None if body is None else json.dumps(body).encode(),headers=headers or {'Content-Type':'application/json'}),timeout=15) as r:return json.load(r)
    def api(path,body=None):return request(f'http://127.0.0.1:{descriptor["port"]}/api/'+path,body,{'Content-Type':'application/json','X-Tracker-Token':descriptor['token']})
    def state():return api('state')
    def select(tag):
        request(printer+'/event',dict(action='tag',tag=tag));uid=tag['uid'] if tag else None
        wait(lambda:any(r.get('uid')==uid for r in state()['occupied']) if uid else not any(r.get('uid') for r in state()['occupied']))
    def launch():
        nonlocal app,descriptor
        old=descriptor.get('token')
        app=subprocess.Popen([str(args.exe.absolute())],env=dict(os.environ,TRACKER20_DATA_DIR=str(profile),TRACKER_BENCH_WEBVIEW_PORT=str(cdp)),stdout=log,stderr=log)
        def ready():
            nonlocal descriptor
            if app.poll() is not None:raise RuntimeError('EXE exited')
            descriptor=json.loads((profile/'instance.json').read_text(encoding='utf-8'))
            return descriptor['token']!=old and state()
        wait(ready)
    def stop():
        if sys.platform=='win32':native_windows(app,out)
        else:app.terminate();app.wait(30)
    try:
        sim=subprocess.Popen([sys.executable,str(Path(__file__).with_name('simulator.py')),printer.rsplit(':',1)[1],'--reader'],stdout=log,stderr=log)
        wait(lambda:request(printer+'/ready'));launch()
        api('settings',dict(values=dict(language='ru',printers=[dict(id='a',name='RFID bench',url=printer)],selected_printer='a',spoolman_url=smurl,spoolman_mode='send'),expected_revision=state()['settings']['revision']))
        api('connections_start',dict(confirmed=True));select(decoded('creality'))
        with sync_playwright() as pw:
            if sys.platform=='win32':
                wait(lambda:request(f'http://127.0.0.1:{cdp}/json/version'))
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp}')
                page=wait(lambda:next((p for c in browser.contexts for p in c.pages if f':{descriptor["port"]}' in p.url),None))
            else:
                browser=pw.chromium.launch();page=browser.new_page();page.goto(f'http://127.0.0.1:{descriptor["port"]}/desktop')
            ui=BrowserEnrollment(page,out)
            ui.apply('creality',decoded('creality')['uid'],remaining=840.123)
            wait(lambda:len(state()['spools'])==1);sid=state()['spools'][0]['spool_id'];assert len(sm.rows['spool'])==1
            checks.append('new spool explicitly confirmed in packaged UI; actual initial remaining 840.123 g')
            sm.rows['spool'][0]['remaining_weight']=623.5
            wait(lambda:state()['spools'][0]['remaining_mg']==623500)
            select(decoded('creality',1));ui.apply('creality',decoded('creality',1)['uid'],sid=sid)
            assert len(sm.rows['spool'])==1 and state()['spools'][0]['remaining_mg']==623500
            checks.append('second tag paired in UI with same Spoolman ID and 623.500 g')
            # Offline dictionary is present inside PyInstaller bundle.
            select(decoded('tigertag'));ui.apply('tigertag',decoded('tigertag')['uid'],remaining=500)
            assert len(sm.rows['spool'])==2
            assert sm.rows['filament'][1]['material']=='PLA' and 'Bambu Lab' in sm.rows['filament'][1]['name']
            checks.append('TigerTag offline manufacturer/material dictionary works inside EXE')
            select(shared_instance_tag());ui.apply('openprinttag',shared_instance_tag()['uid'],remaining=840.123)
            wait(lambda:len(sm.rows['spool'])==3)
            common_sid=next(s['spool_id'] for s in state()['spools'] if s['uid']==shared_instance_tag()['uid'])
            sm.rows['spool'][2]['remaining_weight']=820.123
            select(shared_instance_tag('04052233445502'))
            wait(lambda:any((r.get('spool') or {}).get('spool_id')==common_sid for r in state()['occupied']))
            wait(lambda:next(s for s in state()['spools'] if s['spool_id']==common_sid)['remaining_mg']==820123)
            assert len(sm.rows['spool'])==3
            checks.append('OpenPrintTag explicit instance UUID automatically links second UID without another dialog or spool')
            from tracker_uid import decode_json_tag
            catalog_tag=decode_json_tag(bytes.fromhex('04032233445501'),json.dumps(dict(
                brand='Bambu Lab',material='PLA',color='3F5443',diameter=1.75,weight=1000)).encode())
            select(catalog_tag)
            page.locator('#desktop-tags-refresh').click()
            expect(page.locator('#desktop-rfid-help')).to_contain_text('Alpine Green Sparkle')
            expect(page.locator('#desktop-rfid-density')).to_have_value('1.26')
            expect(page.locator('#desktop-tag-mass')).to_have_value('')
            checks.append('bundled offline SpoolmanDB suggests exact product/density in native EXE; remaining stays blank')
            api('connections_stop',dict(confirmed=True))
        stop();checks.append('native window and actual tray Open/Exit verified')
        launch();api('connections_start',dict(confirmed=True))
        for side in (0,1):
            select(decoded('creality',side))
            wait(lambda:any((r.get('spool') or {}).get('spool_id')==sid for r in state()['occupied']))
            assert next(s for s in state()['spools'] if s['spool_id']==sid)['remaining_mg']==623500
        assert len(sm.rows['spool'])==3 and not sm.puts
        select(shared_instance_tag('04052233445501'))
        wait(lambda:any((r.get('spool') or {}).get('spool_id')==common_sid for r in state()['occupied']))
        assert next(s for s in state()['spools'] if s['spool_id']==common_sid)['remaining_mg']==820123
        checks.append('restart and both tag returns retain spool ID and balance; no tag writes')
        api('connections_stop',dict(confirmed=True));stop()
        # Tester regression in the same ordinary EXE and actual embedded WebView2.
        # A second disposable profile keeps this independent of the RFID inventory.
        from storage import Store
        from backup import create_backup
        from spoolman_bridge import blank,remote_id
        profile=profile.parent/'history-profile';old=Store(profile.parent/'history-fixture')
        remote_sid=remote_id(smurl,1)
        def seed(db):
            db['language']='ru';db['spoolman']=dict(blank(),url=smurl,mode='send',epoch='synthetic')
            db['spools']={remote_sid:dict(name='History PLA',material='PLA',remaining_g=623.5,spoolman=dict(url=smurl,id=1))}
            db['slots']['1']=remote_sid
            db['plans']['p']=dict(filename='native-review.gcode',sha256='a'*64,size=100,weights=[12,0,0,0],spool_ids=[remote_sid,'','',''],created_at=1000,status='review',printer=dict(db['printer']))
            db['runs']['r']=dict(job_id='r',plan_id='p',filename='native-review.gcode',start_time=2000,status='review',physical_weights=[12,0,0,0],physical_spool_ids=[remote_sid,'','',''],tool_mapping=[0,1,2,3])
        old.update(seed);package=create_backup(old,'1.3.3');launch()
        preview=api('validate_backup',dict(package=package));api('restore_backup',dict(package=package,expected_revision=preview['current_revision'],confirmed=True))
        api('settings',dict(values=dict(spoolman_mode='send'),expected_revision=state()['settings']['revision']))
        with sync_playwright() as pw:
            wait(lambda:request(f'http://127.0.0.1:{cdp}/json/version'))
            browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp}')
            page=wait(lambda:next((p for c in browser.contexts for p in c.pages if f':{descriptor["port"]}' in p.url),None))
            page.reload();page.locator('#uid-history-dialog[open]').wait_for();page.locator('#uid-history-edit').click()
            expect(page.locator('.uid-extra-amount')).to_have_value('12')
            expect(page.locator('#uid-review-note')).to_have_value('')
            page.locator('.uid-extra-amount').fill('3.5');page.locator('#uid-review-ack').check()
            page.screenshot(path=str(out/'native-history-prefill.png'));page.locator('#uid-review-apply').click()
            expect(page.locator('#uid-history-send')).to_be_visible()
            assert sm.rows['spool'][0]['remaining_weight']==623.5 and not sm.puts
            page.screenshot(path=str(out/'native-history-send.png'));page.locator('#uid-history-send').click()
            expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman')
            page.screenshot(path=str(out/'native-history-complete.png'))
            assert sm.rows['spool'][0]['remaining_weight']==620 and len(sm.puts)==1
            assert len(state()['debits'])==1 and state()['debits'][0]['delta_mg']==3500
            row=state()['delivery'][0]
            for _ in range(3):assert api('delivery_confirm_send',dict(operation_id=row['operation_id'],expected_revision=row['revision'],request_id='native-repeat',confirmed=True))['status']=='sent'
            assert len(sm.puts)==1
            page.locator('#uid-history-dialog .gd-close').click();page.locator('#nav-history').click()
            expect(page.locator('.history-row')).to_contain_text('Учтено в Tracker')
            expect(page.locator('.history-row')).to_contain_text('отправлено')
        stop();checks.append('native WebView2: saved plan prefill, edited 3.5 g, empty comment, one-window delivery, explicit history status, duplicate confirmations protected')
        (out/'results.json').write_text(json.dumps(dict(success=True,version=VERSION,checks=checks,real_printer_used=False,native_webview2=sys.platform=='win32',remaining_mg=623500),ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        if sys.platform=='win32' and not (out/'results.json').exists():
            from PIL import ImageGrab
            ImageGrab.grab().save(out/'failure-desktop.png')
        if app and app.poll() is None:app.terminate();app.wait(20)
        if sim:sim.terminate();sim.wait(15)
        remote.shutdown();remote.server_close();remote_thread.join();log.close()
        if (profile/'logs/tracker.log').exists():
            import shutil;shutil.copyfile(profile/'logs/tracker.log',out/'tracker.log')


if __name__=='__main__':main()
