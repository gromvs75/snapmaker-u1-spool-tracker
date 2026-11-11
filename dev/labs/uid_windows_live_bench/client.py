"""Frozen Windows GUI against two loopback Klipper/Moonraker process benches."""
import copy,json,sys,tempfile,threading,time,traceback,urllib.request
from pathlib import Path
from types import SimpleNamespace
from tracker_uid_client import UidFleet,PrinterEndpoint
from tracker_uid_runtime import AccountingOwner,PrinterWorkers,ModelInventoryStore
from tracker_uid_gui import serve
from dev.labs.uid_motion_bench import recorder_fixture as recorder


def main(output,manifest):
    import webview,win32api,win32con
    from PIL import ImageGrab
    import tracker_uid_accounting
    cfg=json.loads(Path(manifest).read_text(encoding='utf-8'))
    if cfg.get('kind')!='tracker-process-bench' or cfg.get('printers')!={'a':18781,'b':18782} or cfg.get('control_port')!=18780:
        raise ValueError('Only the fixed loopback process bench is allowed')
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='uid-exe-live-'));offset=[0.]
    tracker_uid_accounting.time=SimpleNamespace(time=lambda:time.time()+offset[0],monotonic=time.monotonic)
    result={'success':False,'frozen':bool(getattr(sys,'frozen',False)),'checks':[],'executable':sys.executable}
    def http(port,path,body=None,control=False):
        headers={'Content-Type':'application/json'}
        if control:headers['X-Bench-Token']=cfg['token']
        req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=50 if control else 3) as response:return json.load(response)
    def control(action,pid):return http(18780,'/',{'action':action,'printer':pid},True)
    def event(pid,action,**kw):return http(cfg['printers'][pid],'/printer/bench_motion/event',dict(action=action,**kw))
    def wait(fn,timeout=45):
        end=time.monotonic()+timeout;error=None
        while time.monotonic()<end:
            try:
                value=fn()
                if value:return value
            except Exception as exc:error=exc
            time.sleep(.15)
        raise AssertionError('Timed out: '+str(error))
    def record(name,condition=True):
        if not condition:raise AssertionError(name)
        result['checks'].append(name)
    fleet=UidFleet([PrinterEndpoint(p,p,f'http://127.0.0.1:{port}') for p,port in cfg['printers'].items()],poll_interval=.3,response_timeout=2,reconnect_max=1)
    owner=None;server=None;workers=[];window=None
    histories={}
    try:
        fleet.start();wait(lambda:all(s['state']=='ready' for s in fleet.snapshot().values()),90)
        owner=AccountingOwner(root/'queue.sqlite',fleet)
        for pid,name,mass,ch in [('a','Чёрный PLA',500000,'0'),('b','Оранжевый PETG',300000,'1')]:
            owner.call('register_manual',name,mass,spool_id='manual-'+pid,details={'material':'PLA'})
            owner.call('assign_manual',pid,ch,'manual-'+pid,confirmed=True)
        owner.close();owner=AccountingOwner(root/'queue.sqlite',fleet)
        server=serve(owner,fleet,0,status_reader=lambda pid:http(cfg['printers'][pid],'/printer/objects/query?print_stats')['result']['status']['print_stats']['state'])
        threading.Thread(target=server.serve_forever,daemon=True).start()
        display=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS);display.PelsWidth=1920;display.PelsHeight=1080
        assert win32api.ChangeDisplaySettings(display,0)==0
        window=webview.create_window('Tracker 2.0 EXE · два процессных стенда',f'http://127.0.0.1:{server.server_port}',width=1375,height=1000,x=20,y=20)
        def js(code):return window.evaluate_js(code)
        def point(selector):
            from System import Func
            from System.Drawing import Point
            r=js(f'(()=>{{const e=document.querySelector({json.dumps(selector)});e.scrollIntoView({{block:"center"}});const r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2,s:devicePixelRatio}}}})()')
            origin=window.native.Invoke(Func[Point](lambda:window.native.webview.PointToScreen(Point(0,0))))
            return int(origin.X+r['x']*r['s']),int(origin.Y+r['y']*r['s'])
        def click(selector):
            import ctypes
            x,y=point(selector);ctypes.windll.user32.SetCursorPos(x,y)
            ctypes.windll.user32.mouse_event(2,0,0,0,0);ctypes.windll.user32.mouse_event(4,0,0,0,0);time.sleep(.25)
        def refresh():js('renderedState="";load()');time.sleep(.8)
        def shot(name):time.sleep(1);ImageGrab.grab().save(out/(name+'.png'))
        def confirm(pid):
            refresh();click(f'[data-printer={pid}] [data-spool=manual-{pid}] button');click('#ack');click('#submit');wait(lambda:js('!$("dialog").open'));refresh()
        def transfer(src,dst):
            import ctypes
            refresh();x,y=point(f'[data-printer={src}] [data-spool=manual-a] h3');tx,ty=point(f'[data-printer={dst}] h3')
            ctypes.windll.user32.SetCursorPos(x,y);ctypes.windll.user32.mouse_event(2,0,0,0,0)
            try:
                for i in range(1,21):ctypes.windll.user32.SetCursorPos(x+(tx-x)*i//20,y+(ty-y)*i//20);time.sleep(.025)
            finally:ctypes.windll.user32.mouse_event(4,0,0,0,0)
            wait(lambda:js('$("dialog").open'));shot('transfer-'+src+'-'+dst)
            click('#ack');click('#submit');wait(lambda:js('!$("dialog").open'));refresh()
        def subscribed(pid):return all(http(cfg['printers'][pid],'/printer/objects/query?bench_motion')['result']['status']['bench_motion']['subscribers'])
        def start_workers():
            for pid,head in [('a',0),('b',1)]:
                port=cfg['printers'][pid];store=ModelInventoryStore(owner,pid,root/('store-'+pid),{'enabled':True,'host':'127.0.0.1','port':port})
                def history_reader(pid=pid,port=port,store=store):
                    jobs=http(port,'/server/history/list?limit=100&order=desc')['result']['jobs'];histories[pid]=copy.deepcopy(jobs)
                    if jobs:
                        job=jobs[0];store._motion_slicer_profile={'filename':job['filename'],'started_at':job['start_time'],'mapping':[0,1,2,3],'replenished':[0,1,2,3],'logical_weights':[1,1,1,1],'filament_type':'PLA;PLA;PLA;PLA','parameters':[{'diameter_mm':1.75,'density_g_cm3':1.24} for _ in range(4)]}
                    return jobs
                def factory(proxy,printer_id,store=store,head=head):return recorder.MotionStreamRecorder(store,lifecycle=proxy,printer_id=printer_id,channels=[str(head)])
                worker=PrinterWorkers(owner,pid,factory,lambda port=port:recorder.WebSocket('127.0.0.1',port),history_reader,store.read()['printer'],poll_interval=.2,reconnect_interval=.3)
                workers.append(worker);worker.start()
            for pid in cfg['printers']:wait(lambda pid=pid:subscribed(pid))
        def exercise():
            nonlocal owner,server
            try:
                wait(lambda:js('typeof state!=="undefined"&&state?.spools?.length===2'))
                result['user_agent']=js('navigator.userAgent');record('native frozen GUI connected to two live UID services',result['frozen'])
                confirm('a');confirm('b');transfer('a','b');transfer('b','a')
                record('GUI confirmations and roundtrip transfer preserve initial balances',sorted(s['remaining_mg'] for s in owner.call('inspect')['spools'])==[300000,500000])
                start_workers();record('two actual Moonraker motion subscriptions')
                for pid in ['a','b']:event(pid,'start',filename='first-'+pid+'.gcode')
                wait(lambda:len(owner.call('inspect')['jobs'])==2);wait(lambda:all(histories.get(p) for p in ['a','b']))
                refresh();record('GUI blocks transfer while printing',js('document.querySelector("[data-printer=a] [data-spool] button").disabled'))
                for pid,h in [('a',0),('b',1)]:event(pid,'motion',head=h,length=100,stamp=1)
                time.sleep(.7);event('a','cancel');event('b','complete')
                wait(lambda:len(owner.call('inspect')['debits'])==2)
                record('real Moonraker terminal histories debit both spools once',sorted(s['remaining_mg'] for s in owner.call('inspect')['spools'])==[299702,499702])
                for _ in range(5):
                    for pid in ['a','b']:owner.call('history',pid,copy.deepcopy(histories[pid]))
                record('ten repeated real history batches do not double debit',len(owner.call('inspect')['debits'])==2)
                for pid in ['a','b']:event(pid,'start',filename='second-'+pid+'.gcode')
                wait(lambda:len(owner.call('inspect')['jobs'])==4)
                for pid,h in [('a',0),('b',1)]:event(pid,'motion',head=h,length=100,stamp=10)
                generation=fleet.snapshot()['a']['connections'];result['stop']=control('stop','a')
                wait(lambda:fleet.snapshot()['a']['state']=='offline');owner.call('refresh');event('b','complete')
                wait(lambda:len(owner.call('inspect')['debits'])==3);refresh();shot('offline')
                record('B finishes while actual Moonraker A process is stopped',js('!state.printers.find(p=>p.id==="a").ready'))
                result['restart']=control('start','a');wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>generation);wait(lambda:subscribed('a'))
                wait(lambda:any(not j['mapping_valid'] and j['state']=='active' for j in owner.call('inspect')['jobs'] if j['printer_id']=='a'))
                record('reconnect does not invent another start or debit',len(owner.call('inspect')['jobs'])==4 and len(owner.call('inspect')['debits'])==3)
                refresh();click('[data-printer=a] > button');click('#stoppedAck');click('#lossAck');click('#resolveSubmit')
                wait(lambda:js('$("resolveError").textContent.length>0'));record('live printing status rejects unsafe GUI resolution');click('#resolveCancel')
                event('a','cancel');time.sleep(.7);refresh();click('[data-printer=a] > button');click('#stoppedAck');click('#lossAck');click('#resolveSubmit');wait(lambda:js('!$("resolveDialog").open'))
                offset[0]=901;refresh();record('temporary unlock expires in EXE',js('state.jobs.some(j=>j.unlock?.expired)'));shot('expired')
                click('[data-printer=a] > button');click('[name=unlockMode][value=until_assignment]');click('#stoppedAck');click('#lossAck');click('#resolveSubmit');wait(lambda:js('!$("resolveDialog").open'))
                confirm('a');transfer('a','b');transfer('b','a')
                record('resolution and GUI transfer create no extra debit',len(owner.call('inspect')['debits'])==3 and len(owner.call('inspect')['resolutions'])==1)
                for _ in range(5):
                    for pid in ['a','b']:owner.call('history',pid,copy.deepcopy(histories[pid]))
                record('late real histories after resolution remain fenced',len(owner.call('inspect')['debits'])==3)
                event('a','start',filename='after-resolution.gcode');wait(lambda:len(owner.call('inspect')['jobs'])==5)
                wait(lambda:any(j['filename']=='after-resolution.gcode' for j in histories['a']))
                event('a','motion',head=0,length=100,stamp=20);time.sleep(.7);event('a','complete');wait(lambda:len(owner.call('inspect')['debits'])==4)
                refresh();shot('completed');record('new confirmed job accounts after resolution',sorted(s['remaining_mg'] for s in owner.call('inspect')['spools'])==[299404,499404])
                for worker in workers:worker.stop()
                workers.clear();server.shutdown();server.server_close();server=None
                owner.close();owner=AccountingOwner(root/'queue.sqlite',fleet)
                for pid,port in cfg['printers'].items():
                    jobs=http(port,'/server/history/list?limit=100&order=desc')['result']['jobs']
                    for _ in range(3):owner.call('history',pid,jobs)
                final=owner.call('inspect');record('SQLite reopen and six real history replays keep exactly four debits',len(final['debits'])==4 and sorted(s['remaining_mg'] for s in final['spools'])==[299404,499404])
                result['success']=True
            except BaseException:
                result['error']=traceback.format_exc()
                try:shot('failure')
                except Exception:pass
            finally:
                result['state']=owner.call('inspect');result['fleet']=fleet.snapshot();result['histories']=histories
                (out/'live-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');window.destroy()
        webview.start(exercise,gui='edgechromium',private_mode=True,storage_path=str(root/'webview'))
    finally:
        for worker in workers:worker.stop()
        if server:server.shutdown();server.server_close()
        if owner:owner.close()
        fleet.stop()
        import shutil
        if (root/'queue.sqlite').exists():shutil.copy2(root/'queue.sqlite',out/'queue.sqlite')
    if not result['success']:raise RuntimeError(result.get('error','Window did not complete'))
