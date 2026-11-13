"""Real localhost Klipper/Moonraker, synthetic motion, real history and queue."""
from pathlib import Path
import sys, json, tempfile, shutil, time, importlib.util, copy, threading, argparse
REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'src'), str(REPO), str(REPO/'dev/labs/uid_multi_bench')]
import run as multi
from tracker_uid_client import UidFleet, PrinterEndpoint
from tracker_uid_runtime import AccountingOwner, PrinterWorkers, ModelInventoryStore
from tracker_uid_gui import serve
spec = importlib.util.spec_from_file_location('bench_recorder', REPO/'dev/labs/uid_motion_bench/recorder_fixture.py')
recorder_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(recorder_module)
RESULTS = []
def check(name, condition, evidence=None):
    assert condition, name
    RESULTS.append(dict(check=name, passed=True, evidence=evidence)); print('PASS '+name, flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resolve',action='store_true');parser.add_argument('--temporary',action='store_true');args=parser.parse_args()
    if args.temporary:args.resolve=True
    clock_offset=[0.]
    if args.temporary:
        from types import SimpleNamespace
        import tracker_uid_accounting
        tracker_uid_accounting.time=SimpleNamespace(time=lambda:time.time()+clock_offset[0],monotonic=time.monotonic)
    output = REPO/('output/uid-unlock-live-bench' if args.temporary else 'output/uid-resolution-live-bench' if args.resolve else 'output/uid-gui-live-bench'); output.mkdir(parents=True, exist_ok=True)
    multi.ROOT = Path(tempfile.mkdtemp(prefix='uid-gui-live-', dir='/private/tmp'))
    printers=[]; workers=[]; fleet=owner=server=server_thread=None; completed=False
    def checkpoint(phase):
        marker=output/(phase+'.continue')
        marker.unlink(missing_ok=True)
        (output/'phase.json').write_text(json.dumps({'phase':phase,'root':str(multi.ROOT),'url':'http://127.0.0.1:18749'}))
        print('GUI CHECKPOINT '+phase,flush=True)
        multi.wait(marker.exists,timeout=600)
    def start_gui():
        nonlocal server,server_thread
        server=serve(owner,fleet,18749,status_reader=lambda pid:next(p for p in printers if p.pid==pid).http('/printer/objects/query?print_stats')['result']['status']['print_stats']['state'])
        server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
    def stop_gui():
        nonlocal server
        if server:
            server.shutdown();server_thread.join();server.server_close();server=None
    try:
        for pid,port in [('a',18781),('b',18782)]:
            p=multi.Printer(pid,port); printers.append(p)
            shutil.copy2(REPO/'dev/labs/uid_runtime_live_bench/bench_motion.py', p.root/'klipper/klippy/extras/bench_motion.py')
            with (p.data/'config/printer.cfg').open('a') as f: f.write('\n[bench_motion]\n')
            p.start()
        fleet=UidFleet([PrinterEndpoint(p.pid,p.pid,p.url) for p in printers],poll_interval=.3,response_timeout=2,reconnect_max=1)
        fleet.start(); multi.wait(lambda: all(s['state']=='ready' for s in fleet.snapshot().values()))
        a,b=printers
        db=multi.ROOT/'queue.sqlite'
        owner=AccountingOwner(db,fleet)
        owner.call('register_manual','Чёрный PLA',500000,spool_id='manual-a',details={'material':'PLA'})
        owner.call('register_manual','Оранжевый PETG',300000,spool_id='manual-b',details={'material':'PLA'})
        owner.call('assign_manual','a','0','manual-a',confirmed=True)
        owner.call('assign_manual','b','1','manual-b',confirmed=True)
        owner.close();owner=AccountingOwner(db,fleet)
        start_gui();checkpoint('initial')
        check('GUI confirms manual assignments on live fleet',all(r['confirmed'] for r in owner.call('inspect')['manual_assignments']))
        check('GUI transfers preserve balances',sorted(s['remaining_mg'] for s in owner.call('inspect')['spools'])==[300000,500000])
        generation=fleet.snapshot()['a']['connections']
        a.stop_m();multi.wait(lambda:fleet.snapshot()['a']['state']=='offline')
        owner.call('refresh')
        a.start_m();multi.wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>generation)
        checkpoint('idle-reconnected')
        check('idle reconnect allows confirmed GUI transfer without debit',len(owner.call('inspect')['debits'])==0 and all(r['confirmed'] for r in owner.call('inspect')['manual_assignments']))
        histories={};stores=[]
        for p,head in zip(printers,[0,1]):
            store=ModelInventoryStore(owner,p.pid,multi.ROOT/('store-'+p.pid),{'enabled':True,'host':'127.0.0.1','port':p.port})
            stores.append(store)
            def history_reader(p=p,store=store):
                jobs=p.http('/server/history/list?limit=100&order=desc')['result']['jobs']
                histories[p.pid]=copy.deepcopy(jobs)
                if jobs:
                    job=jobs[0]
                    store._motion_slicer_profile={'filename':job['filename'],'started_at':job['start_time'],
                        'mapping':[0,1,2,3],'replenished':[0,1,2,3],'logical_weights':[1,1,1,1],
                        'filament_type':'PLA;PLA;PLA;PLA',
                        'parameters':[{'diameter_mm':1.75,'density_g_cm3':1.24} for _ in range(4)]}
                return jobs
            def factory(proxy,pid,store=store,head=head):
                return recorder_module.MotionStreamRecorder(store,lifecycle=proxy,printer_id=pid,channels=[str(head)])
            w=PrinterWorkers(owner,p.pid,factory,lambda p=p:recorder_module.WebSocket('127.0.0.1',p.port),history_reader,
                             store.read()['printer'],poll_interval=.2,reconnect_interval=.3)
            workers.append(w);w.start()
        def subscribed(p):
            return all(p.http('/printer/objects/query?bench_motion')['result']['status']['bench_motion']['subscribers'])
        for p in printers:multi.wait(lambda p=p:subscribed(p))
        check('two real Klipper motion subscriptions through Moonraker',True)
        def event(p,action,**kw):return p.http('/printer/bench_motion/event',dict(action=action,**kw))
        for p in printers:event(p,'start',filename='first-'+p.pid+'.gcode')
        multi.wait(lambda:len(owner.call('inspect')['jobs'])==2)
        multi.wait(lambda:all(histories.get(p.pid) for p in printers))
        check('real Moonraker history linked to two observed starts',True,histories)
        checkpoint('printing')
        for p,h in zip(printers,[0,1]):event(p,'motion',head=h,length=100,stamp=1)
        time.sleep(.5)
        event(a,'cancel');event(b,'complete')
        report=multi.wait(lambda: (r if len(r['debits'])==2 else None) if (r:=owner.call('inspect')) else None)
        check('real history terminals debit once',sorted(s['remaining_mg'] for s in report['spools'])==[299702,499702],report)
        for _ in range(5):
            for p in printers:owner.call('history',p.pid,histories[p.pid])
        check('repeated live history adds no debits',len(owner.call('inspect')['debits'])==2)
        # Second capture is interrupted while the other printer finishes normally.
        for p in printers:event(p,'start',filename='second-'+p.pid+'.gcode')
        multi.wait(lambda:len(owner.call('inspect')['jobs'])==4)
        for p,h in zip(printers,[0,1]):event(p,'motion',head=h,length=100,stamp=10)
        generation=fleet.snapshot()['a']['connections'];a.stop_m()
        multi.wait(lambda:fleet.snapshot()['a']['state']=='offline')
        event(b,'complete')
        multi.wait(lambda:len(owner.call('inspect')['debits'])==3)
        checkpoint('offline')
        check('other printer completes during Moonraker outage',True)
        a.start_m();multi.wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>generation)
        multi.wait(lambda:subscribed(a))
        if not args.resolve:event(a,'cancel')
        multi.wait(lambda:any(j['status'] in ('server_exit','interrupted','cancelled') and j['filename']=='second-a.gcode' for j in histories.get('a',[])))
        report=owner.call('inspect')
        check('reconnect mid-print blocks consumption without creating new start',len(report['jobs'])==4 and len(report['debits'])==3 and any(not j['mapping_valid'] for j in report['jobs'] if j['printer_id']=='a'),report)
        report=owner.call('inspect')
        pairs=[(r['job_key'],r['reason']) for r in report['reviews']]
        check('repeated connection errors do not duplicate review rows',len(pairs)==len(set(pairs)),len(pairs))
        checkpoint('reconnected')
        if args.resolve:
            checkpoint('resolve-printing')
            event(a,'cancel')
            if args.temporary:
                checkpoint('window-open')
                window=next(j['unlock'] for j in owner.call('inspect')['jobs'] if j['unlock'])
                generation=fleet.snapshot()['a']['connections'];a.stop_m()
                multi.wait(lambda:fleet.snapshot()['a']['state']=='offline')
                checkpoint('window-offline')
                clock_offset[0]=901
                a.start_m();multi.wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>generation)
                multi.wait(lambda:subscribed(a))
                current=next(j['unlock'] for j in owner.call('inspect')['jobs'] if j['unlock'])
                check('deadline expires across reconnect without extension',current['expired'] and current['deadline']==window['deadline'],current)
                stop_gui()
                for w in workers:w.stop()
                previous=workers;workers=[];owner.close();owner=AccountingOwner(db,fleet)
                for store in stores:store.owner=owner
                for old in previous:
                    w=PrinterWorkers(owner,old.printer_id,old.recorder_factory,old.socket_factory,old.history_reader,old.config,poll_interval=.2,reconnect_interval=.3)
                    workers.append(w);w.start()
                for p in printers:multi.wait(lambda p=p:subscribed(p))
                current=next(j['unlock'] for j in owner.call('inspect')['jobs'] if j['unlock'])
                check('expired pending window survives owner restart',current['expired'] and current['deadline']==window['deadline'])
                start_gui();checkpoint('window-expired')
                checkpoint('window-renew')
                clock_offset[0]=1802
                current=next(j['unlock'] for j in owner.call('inspect')['jobs'] if j['unlock'])
                check('confirmed window does not relock after next deadline',current['completed'] and not current['expired'])
            else:checkpoint('resolve')
            report=owner.call('inspect')
            check('manual resolution releases only interrupted job with no debit',len(report['resolutions'])==1 and len(report['debits'])==3 and sum(j['state']=='resolved' for j in report['jobs'])==1,report)
            for _ in range(5):
                for p in printers:
                    jobs=copy.deepcopy(histories[p.pid])
                    for j in jobs:
                        if j['filename']=='second-a.gcode':j['status']='cancelled'
                    owner.call('history',p.pid,jobs)
            check('late corrected history after resolution cannot debit',len(owner.call('inspect')['debits'])==3)
            event(a,'start',filename='after-resolution.gcode')
            multi.wait(lambda:len(owner.call('inspect')['jobs'])==5)
            event(a,'motion',head=0,length=100,stamp=20);time.sleep(.5);event(a,'complete')
            multi.wait(lambda:len(owner.call('inspect')['debits'])==4)
            check('new confirmed job after resolution accounts normally',sorted(s['remaining_mg'] for s in owner.call('inspect')['spools'])==[299404,499404])
        stop_gui()
        for w in workers:w.stop()
        workers=[];owner.close();owner=AccountingOwner(db,fleet)
        for p in printers:
            jobs=p.http('/server/history/list?limit=100&order=desc')['result']['jobs']
            for _ in range(3):owner.call('history',p.pid,jobs)
        final=owner.call('inspect')
        check('reopen SQLite and replay real history does not debit twice',len(final['debits'])==(4 if args.resolve else 3) and sorted(s['remaining_mg'] for s in final['spools'])==[299404,499404 if args.resolve else 499702],final)
        start_gui();checkpoint('reopened')
        completed=True
    finally:
        stop_gui()
        for w in workers:w.stop()
        if owner:owner.close()
        if fleet:fleet.stop()
        cleanup_errors=[]
        for p in printers:
            try:
                p.stop_m();p.stop_k()
                cfg=p.data/'config/printer.cfg'
                cfg.write_text(cfg.read_text().replace('\n[bench_motion]\n',''))
                p.close()
            except Exception as exc: cleanup_errors.append(str(exc))
        if cleanup_errors: completed=False

        for p in printers:
            for name in ('klippy','moonraker'):
                log=p.data/f'logs/{name}.log'
                if log.exists():shutil.copy2(log,output/f'{p.pid}-{name}.log')
        if (multi.ROOT/'queue.sqlite').exists():shutil.copy2(multi.ROOT/'queue.sqlite',output/'queue.sqlite')
        (output/'results.json').write_text(json.dumps(dict(completed=completed,root=str(multi.ROOT),checks=RESULTS,cleanup_errors=cleanup_errors),indent=2))
    if cleanup_errors: raise RuntimeError('Stand cleanup failed: '+repr(cleanup_errors))
    print(f'{len(RESULTS)} live queue checks passed; processes stopped and UID modules rolled back',flush=True)

if __name__=='__main__':main()
