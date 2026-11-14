"""Current EXE + two real process printers: UID swap, sleep, GUI review, restore."""
import argparse,json,re,subprocess,tempfile,time,urllib.request
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--browser',action='store_true');a=p.parse_args()
    cfg=json.loads(a.manifest.read_text(encoding='utf-8'))
    assert cfg['kind']=='tracker-process-bench' and cfg['printers']=={'a':18781,'b':18782}
    a.output.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='uid-recovery-exe-'));checks=[];app=None;token=None
    def http(port,path,data=None,headers=None):
        r=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        with urllib.request.urlopen(r,timeout=30) as response:return json.load(response)
    def api(route,data=None):return http(18783,'/api/'+route,data,{'X-Tracker-Token':token})
    def wait(fn,timeout=90):
        end=time.monotonic()+timeout;last=None
        while time.monotonic()<end:
            try:
                value=fn()
                if value:return value
            except Exception as exc:last=str(exc)
            time.sleep(.2)
        raise AssertionError('Timed out: '+str(last))
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    def launch():
        nonlocal token
        proc=subprocess.Popen([str(a.exe.resolve()),'--data',str(root),'--port','18783','--allow-url','http://127.0.0.1:18781','--allow-url','http://127.0.0.1:18782'],cwd=root)
        def ready():
            nonlocal token
            with urllib.request.urlopen('http://127.0.0.1:18783',timeout=2) as r:html=r.read().decode()
            token=json.loads(re.search(r'const TOKEN=("[^"]+");',html)[1]);return True
        try:wait(ready)
        except BaseException:proc.terminate();proc.wait(15);raise
        return proc
    def event(pid,action,**kw):return http(cfg['printers'][pid],'/printer/bench_motion/event',dict(action=action,**kw))
    def scan(pid,ch,uid):
        http(cfg['printers'][pid],'/printer/bench_radio/set_tag',dict(channel=ch,uid=uid))
        http(cfg['printers'][pid],'/printer/bench_radio/scan',dict(channel=ch))
    def connected():return len(api('state')['printers'])==2 and all(p['ready'] for p in api('state')['printers'])
    def balances():return {s['uid']:s['remaining_mg'] for s in api('state')['spools']}
    def register(pid,ch,uid,grams):
        scan(pid,ch,uid)
        preview=wait(lambda:api('tag_preview',dict(printer_id=pid,channel=str(ch),uid=uid)))
        return api('tag_register',dict(printer_id=pid,channel=str(ch),uid=uid,expected_observation=preview['observation_revision'],request_id='register-'+uid,confirmed=True,name='Bench '+uid,remaining_g=grams,material='PLA'))
    try:
        app=launch();s=api('state');api('settings',dict(values={'printers':[dict(id=pid,name='Process '+pid,url=f'http://127.0.0.1:{port}') for pid,port in cfg['printers'].items()]},expected_revision=s['settings']['revision']))
        api('connections_start',{'confirmed':True});wait(connected)
        for pid,old,new in [('a','04112233','04CCCCDD'),('b','04112244','04EEEEFF')]:
            event(pid,'auto_mode',enabled=0)
            register(pid,3,old,20);register(pid,2,new,100)
            http(cfg['printers'][pid],'/printer/bench_radio/clear',dict(channel=2))
        wait(lambda:len(api('state')['spools'])==4)
        wait(lambda:all(all(http(port,'/printer/objects/query?bench_transition')['result']['status']['bench_transition']['subscribers']) for port in cfg['printers'].values()))
        for pid in cfg['printers']:event(pid,'start',filename='recovery.gcode')
        wait(lambda:len(api('state')['recovery_plans'])==2)
        check('EXE registers four observed UIDs and saves both active plans',all(p['auto_replenish'] is False for p in api('state')['recovery_plans']))
        for pid in cfg['printers']:event(pid,'motion',head=3,length=100,stamp=1);event(pid,'pause')
        time.sleep(2);scan('a',3,'04CCCCDD')
        wait(lambda:any(json.loads(e['payload'])['proven'] for e in api('state')['replacement_events']))
        api('connections_stop',{'confirmed':True});app.terminate();app.wait(15);app=None
        scan('b',3,'04EEEEFF')
        for pid in cfg['printers']:event(pid,'resume');event(pid,'motion',head=3,length=900,stamp=10);event(pid,'complete')
        app=launch();api('connections_start',{'confirmed':True});wait(connected)
        wait(lambda:len(api('state')['debits'])==2)
        wait(lambda:len(api('state')['replacement_events'])==2)
        check('EXE restart recovers known paused segments exactly once',balances()['04112233']==19702 and balances()['04CCCCDD']==97315)
        check('unseen replacement during sleep stays pending',balances()['04112244']==20000 and balances()['04EEEEFF']==100000)
        job=next(j for j in api('state')['jobs'] if j['printer_id']=='b' and j['state']=='active')
        review=api('reconcile_preview',dict(job_key=job['job_key']))
        allocation={s['spool_id']:500 if s['uid']=='04112244' else 2483 for s in review['candidates']}
        request=dict(job_key=job['job_key'],expected_revision=review['revision'],allocations_mg=allocation,note='Verified process bench replacement while asleep',request_id='exe-review-decision',confirmed=True)
        if a.browser:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1200,'height':900});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:18783');page.locator('#navHistory').click();page.get_by_role('button',name='Сверить расход',exact=True).click()
                page.locator('#recoveryApply').wait_for();assert page.locator('#recoveryApply').is_disabled()
                for uid,value in [('04112244','0.500'),('04EEEEFF','2.483')]:page.locator('.recovery-spool').filter(has_text='UID '+uid).locator('input').fill(value)
                page.locator('#recoveryNote').fill(request['note']);assert page.locator('#recoveryApply').is_disabled()
                page.locator('#recoveryAck').check();assert page.locator('#recoveryApply').is_enabled()
                page.locator('#historyDetail').screenshot(path=str(a.output/'recovery-form.png'))
                # Lose the successful response once. A repeated identical click must be harmless.
                captured=[]
                def lose(route):
                    captured.append(route.request.post_data_json)
                    response=route.fetch()
                    assert response.status==200
                    route.abort()
                page.route('**/api/reconcile_apply',lose,times=1)
                page.locator('#recoveryApply').click()
                page.wait_for_function("document.querySelector('#workspaceError').textContent.length>0")
                page.locator('#recoveryApply').click()
                page.get_by_text('Решение сохранено. Повторная история не спишет этот расход снова.',exact=True).wait_for()
                request=captured[0]
                page.locator('#historyList').screenshot(path=str(a.output/'recovery-history.png'))
                assert not errors,errors
                browser.close()
            check('GUI confirms once even when successful response is lost',len(api('state')['debits'])==4)
        else:api('reconcile_apply',request)
        assert api('reconcile_apply',request)['status']=='duplicate'
        check('manual review distributes 500 and 2483 mg with idempotent retry',balances()['04112244']==19500 and balances()['04EEEEFF']==97517 and len(api('state')['debits'])==4)
        api('connections_stop',{'confirmed':True});package=api('backup_package',{});v=api('validate_backup',dict(package=package))
        api('restore_backup',dict(package=package,expected_revision=v['current_revision'],confirmed=True))
        api('connections_start',{'confirmed':True});wait(connected);time.sleep(5)
        check('restored receipt and repeated process history do not debit again',len(api('state')['debits'])==4 and balances()['04EEEEFF']==97517)
        api('connections_stop',{'confirmed':True});app.terminate();app.wait(15);app=launch();api('connections_start',{'confirmed':True});wait(connected);time.sleep(5)
        check('second EXE restart keeps ledger and manual decision',len(api('state')['debits'])==4 and api('reconcile_apply',request)['status']=='duplicate')
        (a.output/'recovery-exe-result.json').write_text(json.dumps(dict(success=True,checks=checks,state=api('state'),browser_checked=a.browser),indent=2),encoding='utf-8')
    finally:
        if app and app.poll() is None:app.terminate();app.wait(15)
if __name__=='__main__':main()
