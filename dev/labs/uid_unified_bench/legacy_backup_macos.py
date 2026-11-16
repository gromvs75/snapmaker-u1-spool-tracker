"""Verify an ordinary macOS user bundle with a fresh synthetic profile only.

No printer/Spoolman connections are started. Native Dock policy is read from
NSRunningApplication for the child PID, never from an installed application.
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
import time
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from backup import create_backup
from storage import Store


def wait(check, timeout=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.15)
    raise TimeoutError('Packaged candidate did not reach expected state')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    bundle=args.bundle.resolve();info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    exe=bundle/'Contents/MacOS'/info['CFBundleExecutable']
    root=Path(tempfile.mkdtemp(prefix='tracker-rc3-legacy-native-'))
    data=root/'profile';data.mkdir();env=dict(os.environ,TRACKER20_DATA_DIR=str(data))
    store=Store(root/'synthetic-133')
    def seed(db):
        db.update(language='ru',safety_margin_g=10)
        db['printer'].update(host='127.0.0.1',port=19991,enabled=True)
        db['spools']['native']=dict(name='Synthetic 1.3.3 PLA',material='PLA',remaining_g=125.259,color='#ff7700')
        db['slots']['1']='native'
        db['plans']['saved']=dict(filename='synthetic.gcode',sha256='a'*64,size=10,weights=[12,0,0,0],spool_ids=['native','','',''],created_at=1000,status='committed',printer=dict(db['printer']))
        db['runs']['saved-run']=dict(job_id='native-old',plan_id='saved',start_time=2000,status='committed',filename='synthetic.gcode',physical_weights=[12,0,0,0],physical_spool_ids=['native','','',''],tool_mapping=[0,1,2,3])
    store.update(seed);package=create_backup(store,'1.3.3')
    backup_path=root/'synthetic-1.3.3.json';backup_path.write_text(json.dumps(package))
    original=backup_path.read_bytes();checks=[];app=None;log=(args.output/'native-output.log').open('w')
    def check(name, condition):
        assert condition,name
        checks.append(name);print('PASS '+name,flush=True)
    def api(path, body=None):
        descriptor=json.loads((data/'instance.json').read_text())
        req=Request(f"http://127.0.0.1:{descriptor['port']}"+path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'X-Tracker-Token':descriptor['token'],'Content-Type':'application/json'})
        with urlopen(req,timeout=15) as response:return json.load(response)
    def policy():
        import AppKit
        native=AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(app.pid)
        return native and native.activationPolicy()==AppKit.NSApplicationActivationPolicyAccessory
    def launch():
        nonlocal app
        app=subprocess.Popen([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT)
        wait(lambda:(data/'instance.json').exists() or (app.poll() is not None and (_ for _ in ()).throw(RuntimeError('Application exited'))))
        wait(policy)
        return app
    def stop():
        nonlocal app
        app.send_signal(signal.SIGTERM);app.wait(20)
        check('clean exit and IPC removal',app.returncode==0 and not (data/'instance.json').exists())
        app=None
    try:
        check('bundle menu-bar flag',info.get('LSUIElement') is True)
        launch();check('ordinary launch: Accessory, no Dock tile',policy())
        check('ordinary launch disconnected',api('/api/state')['connections']['connected'] is False)
        second=subprocess.run([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=25)
        check('second writer rejected and window remains Accessory',second.returncode==2 and policy())
        for action in ('hide','show'):
            api('/api/window',dict(action=action));time.sleep(.3)
            check('window '+action+' preserves Accessory',policy())
        preview=api('/api/validate_backup',dict(package=package))
        check('packaged 1.3.3 validator',preview['source_version']=='1.3.3' and preview['jobs']==1)
        restored=api('/api/restore_backup',dict(package=package,expected_revision=preview['current_revision'],confirmed=True))
        state=api('/api/state');desktop=api('/api/desktop/data')
        check('native package preserves balance, plan and history',state['spools'][0]['remaining_mg']==125259 and len(state['debits'])==1 and len(desktop['saved_history'])==1)
        check('restore never enables connections or sender',not state['connections']['connected'] and state['settings']['values']['spoolman_mode']=='off')
        check('rollback and original copy retained',(data/restored['rollback_file']).exists() and backup_path.read_bytes()==original)
        saved=api('/api/backup_package',{})
        stop();launch()
        current=api('/api/state')
        check('restart preserves inventory/history/settings without duplicate debit',current['spools']==state['spools'] and current['debits']==state['debits'] and current['settings']['values']==state['settings']['values'])
        preview=api('/api/validate_backup',dict(package=saved))
        api('/api/restore_backup',dict(package=saved,expected_revision=preview['current_revision'],confirmed=True))
        check('2.0 backup of imported data restores without double accounting',api('/api/state')['debits']==state['debits'])
        check('reopened window remains out of Dock',policy())
        stop()
        (args.output/'results.json').write_text(json.dumps(dict(bundle=str(bundle),profile=str(data),version=info['CFBundleShortVersionString'],commit=info['TrackerSourceCommit'],dirty=info['TrackerBuildDirty'],checks=checks),indent=2))
    finally:
        if app and app.poll() is None:
            app.terminate()
            try:app.wait(20)
            except subprocess.TimeoutExpired:app.kill();app.wait()
        log.close()


if __name__=='__main__':main()
