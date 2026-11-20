"""Ordinary packaged app: tangle/resume and native history-only recovery.

All servers and profiles are synthetic. Windows uses the EXE's own WebView2.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'src'), str(ROOT/'tests')]
from backup import create_backup
from dev.observer_fixture import payload
from storage import Store
from spoolman_bridge import blank, remote_id
from test_rfid_bambu import Server
from dev.labs.uid_candidate_bench.run import wait, native_windows
from playwright.sync_api import sync_playwright, expect
from tracker_app import VERSION


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-direct-spool-selection', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='tracker-resumed-packaged-'))
    log = (out/'process.log').open('w', encoding='utf-8')
    checks = []; app = sim = None; descriptor = {}; ui_errors = []
    sm = Server()
    sm.rows['spool'] = [dict(id=1, remaining_weight=500, initial_weight=1000,
        used_weight=500, filament=dict(id=1, name='Manual PLA', material='PLA',
        density=1.24, diameter=1.75, color_hex='ffffff', vendor=dict(id=1, name='Generic')))]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def call(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length']))) if self.headers.get('Content-Length') else None
            result, _ = sm.request(self.command, self.path.removeprefix('/api/v1'), body)
            raw = json.dumps(result).encode(); self.send_response(200)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        do_GET = do_POST = do_PUT = call
    remote = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=remote.serve_forever); thread.start()
    smurl = f'http://127.0.0.1:{remote.server_port}'
    printer_port = port(); printer = f'http://127.0.0.1:{printer_port}'; cdp = port()
    profile = root/'profile'
    def request(url, body=None, headers=None):
        with urlopen(Request(url, data=None if body is None else json.dumps(body).encode(),
                headers=headers or {'Content-Type':'application/json'}), timeout=15) as r:
            return json.load(r)
    def event(action, **values): return request(printer+'/event', dict(action=action, **values))
    def api(path, body=None):
        return request(f'http://127.0.0.1:{descriptor["port"]}/api/'+path, body,
            {'Content-Type':'application/json', 'X-Tracker-Token':descriptor['token']})
    def state(): return api('state')
    def launch():
        nonlocal app, descriptor
        old = descriptor.get('token')
        app = subprocess.Popen([str(args.exe.resolve())], env=dict(os.environ,
            TRACKER20_DATA_DIR=str(profile), TRACKER_BENCH_WEBVIEW_PORT=str(cdp)), stdout=log, stderr=log)
        def ready():
            nonlocal descriptor
            if app.poll() is not None: raise RuntimeError('Packaged app exited')
            descriptor = json.loads((profile/'instance.json').read_text(encoding='utf-8'))
            return descriptor['token'] != old and state()
        wait(ready)
    def stop(native=False):
        if native and sys.platform == 'win32': native_windows(app, out)
        else: app.terminate(); app.wait(30)
    def restore(name, linked=False):
        old = Store(root/('fixture-'+name)); sid = remote_id(smurl, 1) if linked else 'manual'
        def seed(data):
            data['language'] = 'ru'
            data['printer'].update(host='127.0.0.1', port=printer_port)
            data['spools'][sid] = dict(name='Manual PLA', material='PLA', remaining_g=500)
            if linked:
                data['spoolman'] = dict(blank(), url=smurl, mode='send', epoch='synthetic')
                data['spools'][sid]['spoolman'] = dict(url=smurl, id=1)
            else: data['slots']['1'] = sid
        old.update(seed); package = create_backup(old, '1.3.3')
        preview = api('validate_backup', dict(package=package))
        api('restore_backup', dict(package=package, expected_revision=preview['current_revision'], confirmed=True))
        return sid
    def connect():
        api('connections_start', dict(confirmed=True))
        wait(lambda: request(printer+'/ready')['result']['motion_clients'])
    try:
        sim = subprocess.Popen([sys.executable, str(Path(__file__).with_name('simulator.py')), str(printer_port)], stdout=log, stderr=log)
        wait(lambda: request(printer+'/ready'))
        for label, reset, omit in [('counter-kept', False, False), ('counter-reset', True, False), ('counter-reset-unannounced', True, True)]:
            profile = root/label; launch(); restore(label); connect()
            wait(lambda: state()['manual_assignments'][0]['confirmed'])
            event('start', filename=label+'.gcode'); wait(lambda: state()['recovery_plans'])
            event('motion', stamp=1, length=100); event('error')
            wait(lambda: any(j['history_status']=='error' for j in state()['jobs']))
            assert not state()['debits']
            event('resume', reset_counter=reset, omit_counter=omit); time.sleep(1)
            event('motion', stamp=2, length=200 if omit else 50); event('complete')
            wait(lambda: state()['debits']); snapshot = state()
            expected = 18420 if reset else 447
            assert sum(d['delta_mg'] for d in snapshot['debits']) == expected, snapshot
            assert snapshot['spools'][0]['remaining_mg'] == 500000-expected
            api('connections_stop', dict(confirmed=True)); connect(); time.sleep(1.2)
            assert len(state()['debits']) == 1
            api('connections_stop', dict(confirmed=True)); stop()
            launch(); assert len(state()['debits']) == 1; stop()
            (out/(label+'.json')).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
            checks.append(label+': correct one-time debit and restart persistence')
            print('PASS '+checks[-1], flush=True)
        # This print finished while Tracker was disconnected: history has no bound capture.
        event('start', filename='unobserved-tangle.gcode'); event('error'); event('resume'); event('complete')
        profile = root/'manual-history'
        metadata = profile/'slices'/'Synthetic project'/'Metadata'
        metadata.mkdir(parents=True)
        plate = metadata/'.42.0.gcode'
        plate.write_bytes(payload('15.08, 2.36').replace(
            b'; printer_model', b'; filament_colour = #FD8008;#000000\n; printer_model'))
        launch(); sid = restore('manual-history', linked=True)
        api('settings', dict(values=dict(spoolman_mode='send'), expected_revision=state()['settings']['revision']))
        connect()
        with sync_playwright() as pw:
            if sys.platform == 'win32':
                wait(lambda: request(f'http://127.0.0.1:{cdp}/json/version'))
                browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp}')
                page = wait(lambda: next((p for c in browser.contexts for p in c.pages if f':{descriptor["port"]}' in p.url), None))
            else:
                browser = pw.chromium.launch(); page = browser.new_page()
                page.goto(f'http://127.0.0.1:{descriptor["port"]}/desktop')
            page.on('pageerror', lambda e: ui_errors.append(str(e)))
            page.locator('#nav-overview').click()
            expect(page.locator('#forecast-status')).to_contain_text('Привязка к головкам проверяется')
            expect(page.locator('#desktop-forecast-materials > span')).to_have_text(
                ['Материал 1 · 15,08 гр.', 'Материал 2 · 2,36 гр.'])
            expect(page.locator('.forecast-material-color').nth(0)).to_have_attribute('title', '#FD8008')
            expect(page.locator('.forecast-material-color').nth(1)).to_have_attribute('title', '#000000')
            expect(page.locator('.forecast-head-note')).to_have_count(0)
            assert not state()['debits'] and not sm.puts
            page.screenshot(path=str(out/'forecast-before-print.png'))
            checks.append('slice: exact grams and colors, no guessed head balances or debit')
            page.locator('#nav-history').click()
            row = page.locator('.history-row').filter(has_text='unobserved-tangle.gcode')
            row.locator('.uid-expand').click()
            page.locator('#uid-history-prepare').click()
            expect(page.locator('#uid-history-spool')).to_have_value('')
            assert not state()['debits']
            amount=page.locator('.uid-extra-amount')
            first_field_present=amount.count()>0
            if args.require_direct_spool_selection:
                expect(amount).to_be_visible()
                expect(page.locator('#uid-history-add-spool')).to_be_hidden()
                assert first_field_present, 'First spool must not require an extra Add click'
            if first_field_present:
                expect(amount).to_be_disabled()
                expect(page.locator('#uid-review-apply')).to_be_disabled()
            page.locator('#uid-history-spool').select_option(sid)
            if not first_field_present:
                # The frozen rc4 executable needs an explicit add for the first spool.
                page.locator('#uid-history-add-spool').click()
            expect(amount).to_be_enabled()
            expect(amount).to_have_value('')
            if args.require_direct_spool_selection:
                expect(page.locator('#uid-history-spool')).to_have_value(sid)
                page.locator('#uid-review-ack').check()
                expect(page.locator('#uid-review-apply')).to_be_disabled()
            amount.fill('3.5'); page.locator('#uid-review-ack').check()
            page.screenshot(path=str(out/'native-manual-selection.png'))
            page.locator('#uid-review-apply').click(); expect(page.locator('#uid-history-send')).to_be_visible()
            assert len(state()['debits']) == 1 and not sm.puts
            page.locator('#uid-history-send').click()
            expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman')
            assert sm.rows['spool'][0]['remaining_weight'] == 496.5 and len(sm.puts) == 1
            page.locator('#uid-history-delivery-refresh').click()
            page.screenshot(path=str(out/'native-manual-sent.png'))
            assert len(state()['debits']) == 1 and len(sm.puts) == 1 and not ui_errors
            api('connections_stop', dict(confirmed=True))
        stop(native=True); launch(); connect(); time.sleep(1.2)
        assert len(state()['debits']) == 1 and len(sm.puts) == 1
        api('connections_stop', dict(confirmed=True)); stop()
        checks.append('history-only: explicit spool + 3.5 g, one Spoolman send, replay/restart deduplicated')
        if args.require_direct_spool_selection:
            checks.append('first spool enables grams without Add; confirmation unavailable with empty grams')
        (out/'results.json').write_text(json.dumps(dict(success=True, version=VERSION,
            commit=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
            checks=checks, native_webview2=sys.platform=='win32', real_printer_used=False,
            rfid_module=False, ui_errors=ui_errors), ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if app and app.poll() is None:
            try: (out/'failure-state.json').write_text(json.dumps(state(), ensure_ascii=False), encoding='utf-8')
            except Exception: pass
            app.terminate(); app.wait(30)
        if sim: sim.terminate(); sim.wait(15)
        remote.shutdown(); remote.server_close(); thread.join(); log.close()
        import shutil
        if (profile/'logs/tracker.log').exists(): shutil.copyfile(profile/'logs/tracker.log', out/'tracker.log')


if __name__ == '__main__': main()
