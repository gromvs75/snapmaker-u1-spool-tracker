"""Two real no-hardware Klipper/Moonraker processes and managed session."""
from pathlib import Path
import sys,json,tempfile,shutil,time,importlib.util
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'dev/labs/uid_multi_bench')]
import run as multi
from tracker_uid_session import Session
from tracker_uid_runtime import PrinterWorkers
spec=importlib.util.spec_from_file_location('runtime_bench',ROOT/'dev/labs/uid_runtime_live_bench/run.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def main():
    out=ROOT/'output/settings-live';out.mkdir(parents=True,exist_ok=True)
    multi.ROOT=Path(tempfile.mkdtemp(prefix='uid-settings-live-',dir='/private/tmp'))
    printers=[];session=None;checks=[];histories={}
    def check(name,ok):
        assert ok,name
        checks.append(name);print('PASS '+name,flush=True)
    try:
        for pid,port in [('a',18761),('b',18762)]:
            p=multi.Printer(pid,port);printers.append(p)
            shutil.copy2(ROOT/'dev/labs/uid_runtime_live_bench/bench_motion.py',p.root/'klipper/klippy/extras/bench_motion.py')
            with (p.data/'config/printer.cfg').open('a') as f:f.write('\n[bench_motion]\n')
            p.start();multi.wait(lambda p=p:p.http('/printer/info')['result']['state']=='ready')
        (out/'ready').write_text(str(multi.ROOT))
        # Optional browser handoff uses only these two loopback endpoints.
        if '--browser' in sys.argv:multi.wait(lambda:(out/'go').exists(),timeout=180)
        byid={p.pid:p for p in printers}
        def factory(owner,config,directory):
            p=byid[config['id']];head=0 if p.pid=='a' else 1
            store=runtime.Store(directory/('motion-'+p.pid),p.port)
            def history():
                jobs=p.http('/server/history/list?limit=100&order=desc')['result']['jobs'];histories[p.pid]=jobs
                if jobs:
                    j=jobs[0];store._motion_slicer_profile={'filename':j['filename'],'started_at':j['start_time'],'mapping':[0,1,2,3],'replenished':[0,1,2,3],'logical_weights':[1]*4,'filament_type':'PLA;PLA;PLA;PLA','parameters':[{'diameter_mm':1.75,'density_g_cm3':1.24} for _ in range(4)]}
                return jobs
            return PrinterWorkers(owner,p.pid,lambda proxy,pid:runtime.recorder_module.MotionStreamRecorder(store,lifecycle=proxy,printer_id=pid,channels=[str(head)]),lambda:runtime.recorder_module.WebSocket('127.0.0.1',p.port),history,store.read()['printer'],poll_interval=.2,reconnect_interval=.3)
        session=Session(multi.ROOT/'app',worker_factory=factory,allowed_urls=[p.url for p in printers])
        rev=session.call('settings')['revision'];session.call('save_settings',values={'printers':[dict(id=p.pid,name=p.pid,url=p.url) for p in printers]},expected_revision=rev)
        session.call('register','04112233','A',500000);session.call('register','04AABBCC','B',300000)
        session.call('connect_printers',confirmed=True)
        multi.wait(lambda:all(s['state']=='ready' for s in session.fleet.snapshot().values()))
        for p,h,uid in zip(printers,[0,1],['04112233','04AABBCC']):p.scan(h,uid)
        multi.wait(lambda:session.fleet.snapshot()['a']['channels']['0']['uid']=='04112233' and session.fleet.snapshot()['b']['channels']['1']['uid']=='04AABBCC')
        def subscribed(p):return all(p.http('/printer/objects/query?bench_motion')['result']['status']['bench_motion']['subscribers'])
        for p in printers:multi.wait(lambda p=p:subscribed(p))
        check('saved GUI model connects two independent collectors',True)
        def event(p,action,**kw):p.http('/printer/bench_motion/event',dict(action=action,**kw))
        for p in printers:event(p,'start',filename='settings-'+p.pid+'.gcode')
        multi.wait(lambda:len(session.call('inspect')['jobs'])==2)
        multi.wait(lambda:len(histories)==2 and all(histories.values()))
        for p,h in zip(printers,[0,1]):event(p,'motion',head=h,length=100,stamp=1)
        time.sleep(.5)
        for p in printers:event(p,'complete')
        multi.wait(lambda:len(session.call('inspect')['debits'])==2)
        check('two collectors debit once',sorted(s['remaining_mg'] for s in session.call('inspect')['spools'])==[299702,499702])
        a=printers[0];generation=session.fleet.snapshot()['a']['connections'];a.stop_m()
        multi.wait(lambda:session.fleet.snapshot()['a']['state']=='offline');a.start_m()
        multi.wait(lambda:session.fleet.snapshot()['a']['state']=='ready' and session.fleet.snapshot()['a']['connections']>generation)
        check('reconnect keeps persistent printer ID',set(session.fleet.snapshot())=={'a','b'})
        session.call('disconnect_printers',confirmed=True)
        package=session.call('backup_package');preview=session.call('validate_backup',package=package)
        session.call('restore_backup',package=package,expected_revision=preview['current_revision'],confirmed=True)
        check('restore leaves connections off and ledger preserved',not session.connected and len(session.call('inspect')['debits'])==2)
        session.call('connect_printers',confirmed=True)
        multi.wait(lambda:all(s['state']=='ready' for s in session.fleet.snapshot().values()))
        for _ in range(5):
            for p in printers:session.call('history',p.pid,histories[p.pid])
        check('restored history and reconnect cannot double debit',len(session.call('inspect')['debits'])==2)
        session.close();session=None
        session=Session(multi.ROOT/'app',worker_factory=factory)
        check('restart loads both settings without auto-connect',len(session.fleet.snapshot())==2 and not session.connected)
        (out/'results.json').write_text(json.dumps(dict(checks=checks,root=str(multi.ROOT),state=session.call('inspect')),indent=2))
    finally:
        if session:session.close()
        for p in printers:
            p.stop_m();p.stop_k()
            cfg=p.data/'config/printer.cfg';cfg.write_text(cfg.read_text().replace('\n[bench_motion]\n',''));p.close()
            for name in ('klippy','moonraker'):shutil.copy2(p.data/f'logs/{name}.log',out/f'{p.pid}-{name}.log')
    print(f'{len(checks)} checks passed; processes stopped',flush=True)

if __name__=='__main__':main()
