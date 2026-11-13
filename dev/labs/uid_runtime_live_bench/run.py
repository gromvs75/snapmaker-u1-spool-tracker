"""Real localhost Klipper/Moonraker, synthetic motion, real history and queue."""
from pathlib import Path
import sys, json, tempfile, shutil, time, importlib.util, copy
REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'src'), str(REPO), str(REPO/'dev/labs/uid_multi_bench')]
import run as multi
from tracker_uid_client import UidFleet, PrinterEndpoint
from tracker_uid_runtime import AccountingOwner, PrinterWorkers
spec = importlib.util.spec_from_file_location('bench_recorder', REPO/'dev/labs/uid_motion_bench/recorder_fixture.py')
recorder_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(recorder_module)
RESULTS = []
def check(name, condition, evidence=None):
    assert condition, name
    RESULTS.append(dict(check=name, passed=True, evidence=evidence)); print('PASS '+name, flush=True)

class Store:
    def __init__(self, directory, port):
        self.directory = directory
        self.data = {'printer': {'enabled': True, 'host': '127.0.0.1', 'port': port},
                     'slots': {str(i+1): 'spool%d'%i for i in range(4)},
                     'spools': {'spool%d'%i: {'name': 'Fixture', 'material': 'PLA', 'remaining_g': 500} for i in range(4)}, 'runs': {}}
    def read(self): return copy.deepcopy(self.data)

def main():
    output = REPO/'output/uid-runtime-live-bench'; output.mkdir(parents=True, exist_ok=True)
    multi.ROOT = Path(tempfile.mkdtemp(prefix='uid-runtime-live-', dir='/private/tmp'))
    printers=[]; workers=[]; fleet=owner=None; completed=False
    try:
        for pid,port in [('a',18741),('b',18742)]:
            p=multi.Printer(pid,port); printers.append(p)
            shutil.copy2(Path(__file__).with_name('bench_motion.py'), p.root/'klipper/klippy/extras/bench_motion.py')
            with (p.data/'config/printer.cfg').open('a') as f: f.write('\n[bench_motion]\n')
            p.start()
        fleet=UidFleet([PrinterEndpoint(p.pid,p.pid,p.url) for p in printers],poll_interval=.3,response_timeout=2,reconnect_max=1)
        fleet.start(); multi.wait(lambda: all(s['state']=='ready' for s in fleet.snapshot().values()))
        a,b=printers
        a.scan(0,'04112233'); b.scan(1,'04AABBCC')
        multi.wait(lambda: fleet.snapshot()['a']['channels']['0']['uid']=='04112233' and fleet.snapshot()['b']['channels']['1']['uid']=='04AABBCC')
        db=multi.ROOT/'queue.sqlite'
        owner=AccountingOwner(db,fleet)
        owner.call('register','04112233','A',500000);owner.call('register','04AABBCC','B',300000)
        histories={}
        for p,head in zip(printers,[0,1]):
            store=Store(multi.ROOT/('store-'+p.pid),p.port)
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
        check('other printer completes during Moonraker outage',True)
        a.start_m();multi.wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>generation)
        multi.wait(lambda:subscribed(a));event(a,'cancel')
        multi.wait(lambda:any(j['status'] in ('server_exit','interrupted','cancelled') and j['filename']=='second-a.gcode' for j in histories.get('a',[])))
        report=owner.call('inspect')
        check('reconnect mid-print blocks consumption without creating new start',len(report['jobs'])==4 and len(report['debits'])==3 and any(not j['mapping_valid'] for j in report['jobs'] if j['printer_id']=='a'),report)
        for w in workers:w.stop()
        workers=[];owner.close();owner=AccountingOwner(db,fleet)
        for p in printers:
            jobs=p.http('/server/history/list?limit=100&order=desc')['result']['jobs']
            for _ in range(3):owner.call('history',p.pid,jobs)
        final=owner.call('inspect')
        check('reopen SQLite and replay real history does not debit twice',len(final['debits'])==3 and sorted(s['remaining_mg'] for s in final['spools'])==[299404,499702],final)
        completed=True
    finally:
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
