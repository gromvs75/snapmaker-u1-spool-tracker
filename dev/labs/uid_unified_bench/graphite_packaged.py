"""Exercise the supplied user bundle on synthetic data, never installed profiles.

Browser interactions use HTML/API served by that executable. A separate native
window capture verifies Cocoa/WebKit rendering, not just a browser screenshot.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from backup import create_backup
from storage import Store
from dev.observer_fixture import payload
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--slice-file',type=Path,help='Offline Snorca output with embedded bed 3 marker')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    bundle=args.bundle.resolve();info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    root=Path(tempfile.mkdtemp(prefix='tracker-graphite-package-'));data=root/'profile'
    colors=['#151a1c','#ffffff','#ff7f26','#2b9c70']
    names=['Generic Basis','Generic Basic','Generic Orange','Generic PLA']
    masses=[571.597,195.82,833.574,886.58]
    old=Store(root/'synthetic-133')
    def seed(d):
        d.update(language='ru',safety_margin_g=10)
        d['printer'].update(host='127.0.0.1',port=19991,enabled=False)
        for i in range(4):
            d['spools'][str(i)]=dict(name=names[i],color=colors[i],material='PLA',remaining_g=masses[i])
            d['slots'][str(i+1)]=str(i)
        for i,grams in enumerate([11.62,34.46,9.125]):
            pid='layout-plan-'+str(i);filename=['plate_PLA_19m53s.gcode','Korper3_PLA_1h2m.gcode','shell_PLA_7h27m.gcode'][i]
            d['plans'][pid]=dict(filename=filename,sha256=str(i)*64,size=10,weights=[grams,0,0,0],spool_ids=['0','','',''],created_at=1794825600+i,status='committed',printer=dict(d['printer']))
            d['runs']['layout-run-'+str(i)]=dict(job_id='layout-history-'+str(i),plan_id=pid,start_time=1794829200+i*600,status='committed',filename=filename,physical_weights=[grams,0,0,0],physical_spool_ids=['0','','',''],tool_mapping=[0,1,2,3])
    old.update(seed);package=create_backup(old,'1.3.3')
    writes=[];probe_calls=[];probe_fault=False
    class FakeSpoolman(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path.startswith('/printer/'):
                probe_calls.append(self.path)
                if probe_fault:self.send_error(503);return
                time.sleep(.2)
                value={'result':{'objects':[]}} if self.path=='/printer/objects/list' else {'result':{'status':{'print_stats':{'state':'standby','filename':''}}}}
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            value={'version':'0.27.1'} if self.path=='/api/v1/info' else [dict(id=i+1,remaining_weight=masses[i],filament=dict(name=names[i],material='PLA',color_hex=colors[i][1:])) for i in range(4)]
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_PUT(self):writes.append(self.path);self.send_error(405)
    fake=ThreadingHTTPServer(('127.0.0.1',0),FakeSpoolman);worker=threading.Thread(target=fake.serve_forever);worker.start()
    log=(out/'process.log').open('w');child=None;checks=[]
    def wait(fn,timeout=40):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                result=fn()
                if result:return result
            except (OSError,ValueError):pass
            if child and child.poll() is not None:raise RuntimeError('Candidate exited')
            time.sleep(.1)
        raise TimeoutError('Packaged UI wait timed out')
    def api(route,body=None):
        descriptor=json.loads((data/'instance.json').read_text())
        request=Request(f'http://127.0.0.1:{descriptor["port"]}/api/'+route,data=None if body is None else json.dumps(body).encode(),headers={'X-Tracker-Token':descriptor['token'],'Content-Type':'application/json'})
        with urlopen(request,timeout=15) as r:return json.load(r)
    try:
        child=subprocess.Popen([str(bundle/'Contents/MacOS'/info['CFBundleExecutable'])],env=dict(os.environ,TRACKER20_DATA_DIR=str(data)),stdout=log,stderr=subprocess.STDOUT)
        wait(lambda:(data/'instance.json').exists())
        first_descriptor=(data/'instance.json').read_bytes()
        second=subprocess.run([str(bundle/'Contents/MacOS'/info['CFBundleExecutable'])],env=dict(os.environ,TRACKER20_DATA_DIR=str(data)),stdout=log,stderr=subprocess.STDOUT,timeout=20)
        assert second.returncode==2 and child.poll() is None
        assert (data/'instance.json').read_bytes()==first_descriptor
        assert not api('state')['connections']['connected']
        checks.append('second packaged instance rejects a second writer and preserves the original instance')
        checked=api('validate_backup',dict(package=package))
        api('restore_backup',dict(package=package,expected_revision=checked['current_revision'],confirmed=True))
        # A newly completed synthetic slice: never read the user's slicer cache.
        metadata=data/'slices'/'Graphite fixture'/'Metadata';metadata.mkdir(parents=True)
        sliced=args.slice_file.read_bytes() if args.slice_file else payload('0, 0, 0, 54.7').replace(b'G1 X1',b'; TRACKER_BED_V1 = 03\nG1 X1')
        (metadata/'.42.0.gcode').write_bytes(sliced)
        wait(lambda:api('desktop/forecast')['entries'] and api('desktop/forecast')['entries'][0].get('plate')==3)
        assert api('desktop/forecast')['entries'][0]['plate_identity']=='gcode_marker_v1'
        checks.append('embedded bed 3 from exact G-code bytes; cache suffix 0 is not used as a bed number')
        descriptor=json.loads((data/'instance.json').read_text())
        url=f'http://127.0.0.1:{descriptor["port"]}/desktop'
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':945,'height':800});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(url);page.wait_for_selector('.graphite-head-art')
            assert page.locator('body.graphite').count()==1
            assert page.locator('.graphite-head-art').count()==4
            assert page.evaluate('getComputedStyle(document.querySelector(".sidebar-slot")).borderRadius')=='10px'
            for language in ['en','de','uk','es','ru']:
                page.locator('#lang-picker').select_option(language);page.wait_for_function('(l)=>currentLang===l',arg=language)
            page.wait_for_function("document.getElementById('forecast-single').textContent==='Стол 3'")
            page.screenshot(path=str(out/'overview.png'),full_page=True);checks.append('packaged Graphite, five languages, heads above live synthetic forecast')
            page.locator('#nav-spools').click();page.screenshot(path=str(out/'library.png'),full_page=True)
            assert page.locator('.spool-inventory th').count()==5
            assert page.locator('.graphite-balance').first.inner_text()=='571,6 гр.'
            assert page.locator('#spools-table input').first.input_value()=='571.597'
            assert all(r.bounding_box()['height']<85 for r in page.locator('#spools-table tr').all())
            page.locator('#nav-history').click();page.screenshot(path=str(out/'history.png'),full_page=True)
            assert page.locator('.history-row').count()==3
            assert page.locator('.history-usage').first.inner_text()=='9,1 гр.'
            page.locator('.history-row .uid-expand').first.click();page.locator('#uid-history-dialog[open]').wait_for()
            page.screenshot(path=str(out/'history-complete.png'),full_page=True);page.keyboard.press('Escape')
            page.locator('#desktop-statistics > summary').click();page.locator('#desktop-statistics-body table').first.wait_for()
            page.screenshot(path=str(out/'statistics.png'),full_page=True)
            page.locator('#nav-spools').click()
            page.locator('[data-inventory-tab=slots]').click();page.screenshot(path=str(out/'heads.png'),full_page=True)
            page.locator('[data-inventory-tab=library]').click()
            page.locator('#inventory-toolbar .sc-open').click();page.locator('#sc-dialog[open]').wait_for();page.screenshot(path=str(out/'compare.png'),full_page=True);page.keyboard.press('Escape')
            page.locator('.graphite-actions-open').first.click();page.screenshot(path=str(out/'spool-actions.png'),full_page=True)
            page.locator('#graphite-spool-actions [data-action=transfer]').click()
            assert page.locator('#desktop-operation-dialog .gs-field').count()==2
            page.screenshot(path=str(out/'transfer.png'),full_page=True);page.keyboard.press('Escape')
            page.locator('.inventory-param-button').first.click()
            assert page.locator('#inventory-param-dialog .gs-footer #cal-save').is_visible()
            page.screenshot(path=str(out/'parameters.png'),full_page=True)
            page.locator('#inventory-param-dialog .gs-edit-color').click()
            assert page.locator('.gs-swatch').count()==34
            assert page.locator('#graphite-color-dialog').evaluate('(e)=>e.scrollHeight<=e.clientHeight+1')
            page.screenshot(path=str(out/'color.png'),full_page=True);page.keyboard.press('Escape')
            checks.append('packaged spool actions, parameters, transfer and 34-color grid; cancel without writes')
            page.locator('#inventory-create').click();page.locator('#inventory-add-dialog[open]').wait_for();page.screenshot(path=str(out/'add.png'),full_page=True);page.locator('#inventory-add-dialog .dialog-close').click()
            page.locator('#desktop-tags-open').click()
            page.wait_for_function('document.getElementById("desktop-tags-message").textContent.length>0 && !document.getElementById("desktop-tags-refresh").disabled')
            page.screenshot(path=str(out/'uid.png'),full_page=True);page.locator('#desktop-tags-close').click()
            page.locator('#nav-settings').click();page.locator('[data-settings-section=spoolman]').click();page.locator('[data-sm-tab=connection]').click()
            page.locator('#sm-url').fill(f'http://127.0.0.1:{fake.server_port}');page.locator('#sm-read').check();page.locator('#sm-save').click()
            page.wait_for_function("desktopSpoolmanData.state.mode==='read'")
            page.locator('#sm-refresh').click();page.locator('[data-sm-tab=spools]').click()
            page.wait_for_selector('.sm-spool-row');assert page.locator('.sm-spool-row').count()==4
            for row,color in zip(page.locator('.sm-spool-row').all(),colors):assert color in row.locator('svg').inner_html()
            page.locator('.sm-spool-row').first.click();page.screenshot(path=str(out/'spoolman.png'),full_page=True)
            checks.append('packaged Spoolman catalog shows all four real fixture colors without writes')
            page.locator('[data-settings-section=printer]').click()
            assert page.locator('.graphite-connection-section #desktop-connections-toggle').is_visible()
            for width in [945,800,1280]:
                page.set_viewport_size({'width':width,'height':800})
                boxes=[page.locator(q).bounding_box() for q in ['.graphite-brand','.top-nav','#lang-picker']]
                assert max(b['y']+b['height']/2 for b in boxes)-min(b['y']+b['height']/2 for b in boxes)<2
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':945,'height':800})
            checks.append('packaged library, history and settings at reference width; single-line navigation at 800–1280 px')
            page.screenshot(path=str(out/'settings.png'),full_page=True)
            page.locator('[data-settings-section=accounting]').click();page.screenshot(path=str(out/'accounting.png'),full_page=True)
            page.locator('[data-settings-section=backup]').click();page.screenshot(path=str(out/'backup.png'),full_page=True)
            page.locator('#lang-picker').click();page.locator('#graphite-language-dialog[open]').wait_for();page.screenshot(path=str(out/'languages.png'),full_page=True);page.keyboard.press('Escape')
            checks.append('packaged completed job, statistics, toolhead assignments, name comparison, accounting, backup page and language dialog')
            # Reproduce a concurrent balance edit against the packaged owner.
            sys.path.insert(0,str(ROOT/'tests'))
            from test_balance_feedback import exercise_balance
            def change_balance_elsewhere():
                current=api('desktop/data');sid=page.locator('#spools-table tr').first.get_attribute('data-spool-id')
                api('desktop/spools/update',dict(id=sid,remaining_g='90',_inventory_revision=current['inventory_revision'],_request_id=__import__('uuid').uuid4().hex,_confirmed=True))
            exercise_balance(page,change_balance_elsewhere,out/'balance-conflict.png')
            page.screenshot(path=str(out/'balance-saved.png'),full_page=True)
            checks.append('packaged balance conflict refreshes automatically, keeps entered amount, requires new acknowledgement; no duplicate confirmation')
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            page.locator('#printer-host').fill('127.0.0.1');page.locator('#printer-port').fill(str(fake.server_port))
            page.locator('#printer-test').click()
            assert page.locator('#printer-test-result').get_attribute('data-state')=='pending'
            page.wait_for_function("document.getElementById('printer-test-result').dataset.state==='ok'")
            page.screenshot(path=str(out/'probe-success.png'),full_page=True)
            assert 'Moonraker отвечает' in page.locator('#printer-test-result').inner_text()
            assert not api('state')['connections']['connected']
            probe_fault=True
            page.locator('#printer-test').click();page.wait_for_function("document.getElementById('printer-test-result').dataset.state==='error'")
            page.screenshot(path=str(out/'probe-failure.png'),full_page=True)
            assert len(probe_calls)==3 and not api('state')['connections']['connected']
            checks.append('packaged one-shot probe: pending, success without UID module, HTTP failure; collectors remain stopped')
            assert not errors,errors
            browser.close()
        assert not api('state')['connections']['connected'] and not writes
        assert sum(d['delta_mg'] for d in api('state')['debits'])==55205
        # Capture only this child PID's native window, not the user's desktop.
        import AppKit,Quartz
        app=AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(child.pid)
        assert app and app.activationPolicy()==1 and str(app.bundleURL().path())==str(bundle)
        api('window',dict(action='hide'));time.sleep(.5)
        assert child.poll() is None and (data/'instance.json').exists()
        api('window',dict(action='show'));time.sleep(2)
        windows=[w for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll,0) if w.get('kCGWindowOwnerPID')==child.pid and w.get('kCGWindowLayer')==0]
        window=max(windows,key=lambda w:w['kCGWindowBounds']['Width']*w['kCGWindowBounds']['Height'])
        subprocess.run(['screencapture','-x','-o','-l',str(window['kCGWindowNumber']),str(out/'native-overview.png')],check=True)
        checks.append('native child window hide/show and capture, Accessory policy, no real connections or new debits')
        child.send_signal(signal.SIGTERM);child.wait(20)
        assert child.returncode==0 and not (data/'instance.json').exists();checks.append('clean packaged exit')
        (out/'results.json').write_text(json.dumps(dict(version=info['CFBundleShortVersionString'],commit=info['TrackerSourceCommit'],dirty=info['TrackerBuildDirty'],profile=str(data),bundle=str(bundle),checks=checks),indent=2))
        print('\n'.join('PASS '+c for c in checks))
    finally:
        if child and child.poll() is None:child.terminate();child.wait(20)
        fake.shutdown();worker.join();fake.server_close();log.close()

if __name__=='__main__':main()
