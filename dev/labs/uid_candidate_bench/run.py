"""Run the ordinary user executable against a disposable stock-U1 simulator.

Tests real collectors inside the packaged app, not a patched accounting sink.
Windows additionally exercises the native window and actual tray Open/Exit.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from backup import create_backup
from storage import Store
from tracker_app import VERSION


def wait(fn,timeout=60):
    end=time.monotonic()+timeout;last=None
    while time.monotonic()<end:
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError,KeyError) as exc:last=str(exc)
        time.sleep(.15)
    raise TimeoutError('Candidate bench timeout: '+str(last))


def native_windows(proc,out):
    import win32gui,win32con,win32api
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    from PIL import ImageGrab
    desktop=Desktop(backend='uia')
    handle=wait(lambda:win32gui.FindWindow(None,f'Snapmaker U1 Spool Tracker {VERSION} · кандидат'))
    wait(lambda:win32gui.IsWindowVisible(handle))
    rect=win32gui.GetWindowRect(handle)
    assert rect[0]>=0 and rect[1]>=0 and rect[2]<=win32api.GetSystemMetrics(0) and rect[3]<=win32api.GetSystemMetrics(1),rect
    ImageGrab.grab().save(out/'native-open.png')
    win32gui.PostMessage(handle,win32con.WM_CLOSE,0,0)
    wait(lambda:not win32gui.IsWindowVisible(handle));assert proc.poll() is None
    def menu(label):
        send_keys('{ESC}');time.sleep(.7)
        bar=desktop.window(class_name='Shell_TrayWnd')
        expand=next((b for b in bar.descendants(control_type='Button') if 'hidden icons' in b.window_text().lower()),None)
        if expand:expand.click_input();time.sleep(.7)
        def icon():
            candidates=bar.descendants(control_type='Button')
            for window in desktop.windows():
                if window.element_info.class_name in ('NotifyIconOverflowWindow','TopLevelWindowForOverflowXamlIsland'):
                    candidates+=window.descendants(control_type='Button')
            return next((b for b in candidates if b.window_text()==f'Tracker {VERSION} · кандидат' and b.is_visible()),None)
        wait(icon,20).click_input(button='right')
        def item():
            for window in desktop.windows():
                for row in window.descendants(control_type='MenuItem'):
                    if row.window_text()==label:return row
        target=wait(item,20)
        ImageGrab.grab().save(out/('tray-open.png' if label.startswith('Открыть') else 'tray-exit.png'))
        target.click_input()
    menu('Открыть Tracker');wait(lambda:win32gui.IsWindowVisible(handle))
    menu('Выход');assert proc.wait(30)==0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='tracker-rc21-native-'));data=root/'profile'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';app=None;descriptor={};checks=[]
    log=(out/'process.log').open('w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,str(Path(__file__).with_name('simulator.py')),str(port)],stdout=log,stderr=log)
    def http(path,body=None):
        request=Request(url+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as response:return json.load(response)['result']
    def event(action,**values):return http('/event',dict(action=action,**values))
    def api(path,body=None):
        request=Request(f'http://127.0.0.1:{descriptor["port"]}/api/'+path,
            data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Tracker-Token':descriptor['token']})
        with urlopen(request,timeout=15) as response:return json.load(response)
    def state():return api('state')
    def check(name):checks.append(name);print('PASS '+name,flush=True)
    def launch():
        nonlocal app,descriptor
        old=descriptor.get('token')
        app=subprocess.Popen([str(args.exe.resolve())],env=dict(os.environ,TRACKER20_DATA_DIR=str(data)),stdout=log,stderr=log)
        def ready():
            nonlocal descriptor
            if app.poll() is not None:raise RuntimeError('Packaged app exited: '+str(app.returncode))
            path=data/'instance.json'
            if not path.exists():return False
            descriptor=json.loads(path.read_text(encoding='utf-8'))
            return descriptor['token']!=old and state()
        wait(ready)
    def stop():
        if sys.platform=='win32':native_windows(app,out)
        else:app.terminate();assert app.wait(30)==0
        assert not (data/'instance.json').exists()
    def connect():
        api('connections_start',dict(confirmed=True))
        wait(lambda:state()['printers'][0]['uid_state']=='module_missing' and http('/ready')['motion_clients']>0)
        wait(lambda:state()['manual_assignments'][0]['confirmed'])
    try:
        wait(lambda:http('/ready'))
        assert 'tracker_uid' not in http('/printer/objects/list')['objects']
        filename='manual-repeat.gcode';event('start',filename=filename);event('complete')
        old_job=http('/server/history/list')['jobs'][0]
        old=Store(root/'synthetic-133')
        def seed(db):
            db['printer'].update(host='127.0.0.1',port=port)
            db['spools']['manual-t0']=dict(name='Synthetic PLA',material='PLA',remaining_g=553.177)
            db['slots']['1']='manual-t0'
            db['plans']['saved']=dict(filename=filename,sha256='a'*64,size=100,weights=[18.42,0,0,0],spool_ids=['manual-t0','','',''],created_at=old_job['start_time'],status='committed',printer=dict(db['printer']))
            db['runs']['old']=dict(job_id=old_job['job_id'],plan_id='saved',start_time=old_job['start_time'],status='committed',filename=filename,physical_weights=[18.42,0,0,0],physical_spool_ids=['manual-t0','','',''],tool_mapping=list(range(4)))
        old.update(seed);package=create_backup(old,'1.3.3')
        launch();assert not state()['connections']['connected'];check('ordinary executable starts disconnected with isolated profile')
        second=subprocess.run([str(args.exe.resolve())],env=dict(os.environ,TRACKER20_DATA_DIR=str(data)),stdout=log,stderr=log,timeout=30)
        assert second.returncode==2 and app.poll() is None;check('second writer rejected')
        preview=api('validate_backup',dict(package=package));api('restore_backup',dict(package=package,expected_revision=preview['current_revision'],confirmed=True))
        assert state()['spools'][0]['remaining_mg']==553177 and len(state()['debits'])==1
        assert state()['settings']['values']['spoolman_mode']=='off';check('1.3.3 restore preserves existing balance and receipt, external send remains off')
        connect();check('manual placement is usable on stock printer with no UID module')
        time.sleep(1.2);event('start',filename=filename)
        wait(lambda:len(state()['recovery_plans'])==2)
        event('history_timeout');wait(lambda:http('/ready')['faults_used']==1)
        wait(lambda:'timed out' in (data/'logs/tracker.log').read_text(encoding='utf-8'))
        time.sleep(1);event('complete');wait(lambda:len(state()['debits'])==2)
        assert state()['spools'][0]['remaining_mg']==534757
        check('observed-start print survives one HTTP timeout and debits 18.420 g once without RFID')
        api('connections_stop',dict(confirmed=True));connect();time.sleep(5)
        assert len(state()['debits'])==2 and state()['spools'][0]['remaining_mg']==534757
        check('history replay and reconnect preserve balance')
        stop();check('native close/real tray Open/Exit verified' if sys.platform=='win32' else 'clean packaged shutdown')
        launch();assert state()['spools'][0]['remaining_mg']==534757 and len(state()['debits'])==2
        connect()
        # Synthetic prints finish in seconds. Keep distinct starts outside the
        # collector's existing 30-second clock-skew window, as real prints are.
        previous_start=http('/server/history/list')['jobs'][0]['start_time']
        time.sleep(max(0,31.5-(time.time()-previous_start)))
        event('start',filename=filename);wait(lambda:len(state()['recovery_plans'])==3)
        event('complete');wait(lambda:len(state()['debits'])==3)
        assert state()['spools'][0]['remaining_mg']==516337
        check('restart and a new print of the same filename add exactly one new debit')
        saved=api('backup_package',{});assert api('validate_backup',dict(package=saved))['spools']==1
        stop();check('backup validates and final exit releases profile')
        (out/'results.json').write_text(json.dumps(dict(success=True,version=VERSION,checks=checks,remaining_mg=516337,
            native_windows_tray_verified=sys.platform=='win32',real_printer_used=False,rfid_module=False),indent=2),encoding='utf-8')
    finally:
        if app and app.poll() is None:app.terminate();app.wait(20)
        server.terminate();server.wait(15);log.close()
        if (data/'logs/tracker.log').exists():
            import shutil;shutil.copy2(data/'logs/tracker.log',out/'tracker.log')


if __name__=='__main__':main()
