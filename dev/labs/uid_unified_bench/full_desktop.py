"""Full published shell with two marked no-hardware Klipper/Moonraker pairs.

The supervisor owns every process; this runner accepts only its fixed loopback
manifest and creates a new temporary profile. No installed app/config discovery.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from tracker_uid_session import Session
from tracker_uid_collectors import ReadOnlyMoonraker,create_workers
from tracker_uid_gui import serve
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.manifest.read_text())
    if config.get('kind')!='tracker-process-bench' or config.get('printers')!={'a':18781,'b':18782} or config.get('control_port')!=18780:raise ValueError('Fixed loopback process bench required')
    args.output.mkdir(parents=True,exist_ok=True);directory=Path(tempfile.mkdtemp(prefix='tracker-full-desktop-'))
    result=dict(success=False,checks=[],data=str(directory));app=None;server=None;thread=None
    def http(pid,path,body=None):
        port=config['printers'][pid] if pid else config['control_port']
        headers={'Content-Type':'application/json'}
        if pid is None:headers['X-Bench-Token']=config['token']
        req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=50 if pid is None else 3) as r:return json.load(r)
    def wait(fn,timeout=45):
        end=time.monotonic()+timeout;last=None
        while time.monotonic()<end:
            try:
                value=fn()
                if value:return value
            except Exception as exc:last=exc
            time.sleep(.1)
        raise AssertionError('Timed out: '+str(last))
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        result['checks'].append(name);print('PASS '+name,flush=True)
    def event(pid,action,**values):return http(pid,'/printer/bench_motion/event',dict(action=action,**values))
    try:
        urls=[f'http://127.0.0.1:{p}' for p in config['printers'].values()]
        app=Session(directory,allowed_urls=urls,worker_factory=create_workers)
        def status(pid):
            p=next(p for p in app.call('settings')['values']['printers'] if p['id']==pid)
            if not app.connected:raise ValueError('Connections stopped')
            return ReadOnlyMoonraker(p['url']).status()['print_stats']['state']
        server=serve(app,app.fleet,status_reader=status,app_info={'version':'2.0.0rc1','mode':'user'})
        thread=threading.Thread(target=server.serve_forever);thread.start()
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1360,'height':1080});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            for pid,port in config['printers'].items():
                page.locator('#desktop-printer-add').click();page.locator('#desktop-printer-name').fill('Process '+pid);page.locator('#printer-host').fill('127.0.0.1');page.locator('#printer-port').fill(str(port))
                with page.expect_response('**/api/settings') as response:page.locator('#printer-save').click()
                assert response.value.ok;page.wait_for_function('(n)=>desktopFormData.printers.length===n',arg=1 if pid=='a' else 2)
                with page.expect_response('**/api/test_printer') as response:page.locator('#printer-test').click()
                assert response.value.ok and response.value.json()['uid_available']
            ids={p['name'][-1]:p['id'] for p in app.call('settings')['values']['printers']}
            check('GUI saves and probes both real process endpoints without starting collectors',not app.connected)
            with page.expect_response('**/api/connections_start') as response:
                page.locator('#desktop-connections-toggle').click();page.locator('#graphite-confirm-apply').click()
            assert response.value.ok
            wait(lambda:all(s['state']=='ready' for s in app.fleet.snapshot().values()))
            for pid,uid in [('a','04112233'),('b','04AABBCC')]:
                event(pid,'auto_mode',enabled=0)
                http(pid,'/printer/bench_radio/set_tag',dict(channel=3,uid=uid));http(pid,'/printer/bench_radio/scan',dict(channel=3))
                wait(lambda:app.fleet.snapshot()[ids[pid]]['channels']['3'].get('uid')==uid)
            page.evaluate('loadData()');page.locator('#nav-spools').click();page.locator('#desktop-tags-open').click()
            for uid in ('04112233','04AABBCC'):
                page.locator(f'#desktop-tags-dialog [data-uid="{uid}"]').click();page.locator('#desktop-tag-name').fill('Process UID '+uid);page.locator('#desktop-tag-material').fill('PLA');page.locator('#desktop-tag-mass').fill('100');page.locator('#desktop-tag-next').click();page.locator('#desktop-tag-ack').check()
                with page.expect_response('**/api/tag_register') as response:page.locator('#desktop-tag-save').click()
                assert response.value.ok;page.wait_for_function('(uid)=>!document.querySelector(`[data-uid="${uid}"]`)',arg=uid)
            page.screenshot(path=str(args.output/'uid-complete.png'),full_page=True);page.locator('#desktop-tags-close').click()
            check('native UID module observations registered through full shell queue',len(app.call('inspect')['spools'])==2)
            # Positive readiness before print start: no historical UID claim is
            # allowed to substitute for a fresh present/absent channel snapshot.
            wait(lambda:all(s['state']=='ready' and s['channels']['3']['state']=='present' and all(s['channels'][str(i)]['state']=='absent' for i in range(3)) for s in app.fleet.snapshot().values()))
            for pid in config['printers']:wait(lambda pid=pid:all(http(pid,'/printer/objects/query?bench_transition')['result']['status']['bench_transition']['subscribers']))
            for pid in config['printers']:event(pid,'start',filename='recovery.gcode')
            wait(lambda:len(app.call('inspect')['recovery_plans'])==2)
            check('both collectors save observed starts and verified slicer plans')
            for pid in config['printers']:
                event(pid,'motion',head=3,length=100,stamp=1);event(pid,'motion',head=3,length=900,stamp=10);event(pid,'complete')
            wait(lambda:len(app.call('inspect')['debits'])==2)
            before=app.call('inspect')['debits'];balances=app.call('inspect')['spools']
            check('two process jobs debit once',all(d['delta_mg']==2983 for d in before))
            history={pid:ReadOnlyMoonraker(f'http://127.0.0.1:{port}').history() for pid,port in config['printers'].items()}
            for _ in range(3):
                for pid in config['printers']:app.call('history',ids[pid],history[pid])
            check('repeated process history leaves ledger unchanged',app.call('inspect')['debits']==before)
            http(None,'/',dict(action='stop',printer='a'));wait(lambda:app.fleet.snapshot()[ids['a']]['state']=='offline')
            check('one Moonraker loss leaves the second connected',app.fleet.snapshot()[ids['b']]['state']=='ready')
            http(None,'/',dict(action='start',printer='a'));wait(lambda:app.fleet.snapshot()[ids['a']]['state']=='ready')
            for pid in config['printers']:app.call('history',ids[pid],history[pid])
            check('reconnect and replay do not charge again',app.call('inspect')['debits']==before and app.call('inspect')['spools']==balances)
            page.evaluate('loadData()');page.locator('#nav-history').click();page.screenshot(path=str(args.output/'process-history.png'),full_page=True)
            page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click();page.locator('#desktop-connections-toggle').click();page.wait_for_function('!desktopFormData.connections.connected')
            check('GUI stops both collectors cleanly',not app.workers and not app.connected and not errors)
            page.locator('#nav-history').click();page.locator('#desktop-statistics summary').click()
            page.wait_for_function('document.getElementById("desktop-statistics-body").textContent.includes("3")')
            check('statistics reads selected printer ledger once',app.call('desktop_statistics')['total_mg']==2983)
            page.screenshot(path=str(args.output/'statistics.png'),full_page=True)
            page.locator('#nav-spools').click();page.locator('#inventory-create').click()
            page.locator('#new-name').fill('Archived spare');page.locator('#new-mat').fill('PLA');page.locator('#new-weight').fill('125.259')
            page.locator('#t-add-btn').click();page.locator('#inventory-add-dialog').wait_for(state='hidden')
            spare=next(s['spool_id'] for s in app.call('library_snapshot')['spools'] if s['name']=='Archived spare')
            page.evaluate('(id)=>window.inventoryParameters(id)',spare)
            page.locator('#cal-diameter').fill('1.751');page.locator('#cal-density').fill('1.244');page.locator('#cal-save').click()
            page.locator('#inventory-param-dialog').wait_for(state='hidden')
            page.locator(f'#spools-table tr[data-spool-id="{spare}"] .graphite-actions-open').click();page.locator('#graphite-spool-actions [data-action=archive]').click();page.locator('#graphite-confirm-apply').click()
            page.wait_for_function('(id)=>desktopFormData.spools[id].archived===true',arg=spare)
            check('parameters and archive preserve exact spare balance',next(s for s in app.call('library_snapshot')['spools'] if s['spool_id']==spare)['remaining_mg']==125259)
            page.locator('#nav-settings').click();page.locator('[data-settings-section=backup]').click()
            with page.expect_download() as download:page.locator('#backup-export').click()
            backup=args.output/'backup.json';download.value.save_as(backup)
            page.locator('#backup-import').click();page.locator('#desktop-backup-file').set_input_files(backup)
            with page.expect_response('**/api/validate_backup') as response:page.locator('#desktop-backup-check').click()
            assert response.value.ok and response.value.json()['debits']==2
            page.locator('#desktop-backup-ack').check()
            with page.expect_response('**/api/restore_backup') as response:page.locator('#desktop-backup-apply').click()
            assert response.value.ok
            page.locator('#desktop-backup-dialog').wait_for(state='hidden')
            check('GUI exports validates and restores checked copy',not app.connected and not errors)
            browser.close()
        for pid in config['printers']:app.call('history',ids[pid],history[pid])
        check('restore keeps both debits and prevents replay',app.call('inspect')['debits']==before)
        result['success']=True
    except BaseException:
        result['error']=traceback.format_exc();raise
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        if app:
            result['final_state']=app.call('inspect');app.close()
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
