"""Research only: service transition on real Klipper/Moonraker processes."""
from pathlib import Path
import sys,json,tempfile,shutil,time,importlib.util,argparse
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'dev/labs/uid_multi_bench')]
import run as multi
from tracker_uid_client import UidFleet,PrinterEndpoint
from tracker_uid_runtime import AccountingOwner,PrinterWorkers
from dev.labs.uid_autorefill_boundary_bench.model import Checkpoint,automatic_boundary,printing_interval,partition_motion,partition_uncertain_fences
spec=importlib.util.spec_from_file_location('rt',ROOT/'dev/labs/uid_runtime_live_bench/run.py');rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scenario',choices=['baseline','late-service'],default='baseline');args=parser.parse_args()
    out=ROOT/'output/autorefill-boundaries-2026-11-14'/args.scenario;out.mkdir(parents=True,exist_ok=True)
    multi.ROOT=Path(tempfile.mkdtemp(prefix='uid-transition-',dir='/private/tmp'))
    p=None;fleet=owner=worker=None;checks=[]
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    try:
        p=multi.Printer('transition',18763)
        for file in [ROOT/'dev/labs/uid_runtime_live_bench/bench_motion.py',Path(__file__).with_name('bench_transition.py')]:shutil.copy2(file,p.root/'klipper/klippy/extras'/file.name)
        with (p.data/'config/printer.cfg').open('a') as f:f.write('\n[bench_transition]\n')
        p.start();fleet=UidFleet([PrinterEndpoint(p.pid,'Transition',p.url)],poll_interval=.2,response_timeout=2)
        fleet.start();multi.wait(lambda:fleet.snapshot()[p.pid]['state']=='ready')
        for head,uid in [(3,'04112233'),(1,'04AABBCC')]:p.scan(head,uid)
        multi.wait(lambda:all(fleet.snapshot()[p.pid]['channels'][str(h)]['uid'] for h in (1,3)))
        owner=AccountingOwner(multi.ROOT/'research.sqlite',fleet)
        for uid in ['04112233','04AABBCC']:owner.call('register',uid,uid,500000)
        store=rt.Store(multi.ROOT/'motion',p.port);history=[]
        def read_history():
            nonlocal history
            history=p.http('/server/history/list?limit=100&order=desc')['result']['jobs']
            if history:
                j=history[0];store._motion_slicer_profile={'filename':j['filename'],'started_at':j['start_time'],'mapping':[0,1,2,3],'replenished':[0,1,2,3],'logical_weights':[1]*4,'filament_type':'PLA;PLA;PLA;PLA','parameters':[{'diameter_mm':1.75,'density_g_cm3':1.24} for _ in range(4)]}
            return history
        worker=PrinterWorkers(owner,p.pid,lambda proxy,pid:rt.recorder_module.MotionStreamRecorder(store,lifecycle=proxy,printer_id=pid,channels=['1','3']),lambda:rt.recorder_module.WebSocket('127.0.0.1',p.port),read_history,store.read()['printer'],poll_interval=.2,reconnect_interval=.3)
        worker.start()
        def status():return p.http('/printer/objects/query?bench_transition')['result']['status']['bench_transition']
        multi.wait(lambda:all(status()['subscribers']))
        def event(action,**kw):p.http('/printer/bench_motion/event',dict(action=action,**kw))
        event('start',filename='service-transition.gcode');multi.wait(lambda:len(owner.call('inspect')['jobs'])==1 and history)
        event('sample',head=3,length=100,stamp=1)
        event('queue_sample',head=3,length=2,stamp=2)
        event('service_pause');time.sleep(.7)
        event('flush') # pre-pause movement arrives during paused state
        event('sample',head=3,length=5,stamp=10,counter=5)
        event('queue_sample' if args.scenario=='late-service' else 'sample',head=1,length=20,stamp=11,counter=7.84003)
        event('service_resume');time.sleep(.7)
        if args.scenario=='late-service':event('flush')
        event('sample',head=1,length=100,stamp=21);time.sleep(.5);event('complete')
        trace=status()['trace']
        check('late pre-pause packet delivered during paused',any(x['kind']=='delivery' and x['stamp']==2 and x['state']=='paused' for x in trace))
        service=[x for x in trace if x['kind']=='command' and 10<=x['stamp']<20]
        naive=sum(x['length'] for x in trace if x['kind']=='delivery' and x['state']=='paused')
        check('arrival-state filtering is wrong',naive==(7 if args.scenario=='late-service' else 27) and sum(x['length'] for x in service)==25)
        if args.scenario=='late-service':check('service motion delivered after printing resumes',any(x['kind']=='delivery' and x['stamp']==11 and x['state']=='printing' for x in trace))
        packets=[dict(id=str(x['stamp'])+':'+str(x['head']),head=x['head'],start=x['stamp'],end=x['stamp']+1,length=x['length'],clock='synthetic-command-clock',epoch='fixture') for x in trace if x['kind']=='delivery']
        partition=partition_motion(list(reversed(packets))+packets,pause_fence=10,resume_fence=20,clock='synthetic-command-clock',epoch='fixture')
        check('event-time partition survives late delivery and exact replay',partition['fully_partitioned'] and sum(x['length'] for x in partition['groups']['service'])==25 and not partition['authorizes_debit'])
        uncertain=partition_uncertain_fences(packets,pause_window=(9,12),resume_window=(19,22),clock='synthetic-command-clock',epoch='fixture')
        check('status uncertainty leaves boundary packets unresolved',not uncertain['fully_partitioned'] and sum(p['length'] for p in uncertain['groups']['ambiguous'])==125 and not uncertain['authorizes_debit'])
        def point(heads,total,fence):return Checkpoint(tuple(heads),total,'synthetic-command-clock',fence,True,('s0','s1','s2','s3'),'fixture')
        before=point([0,0,0,102],102,10);resume=point([0,20,0,107],114.84003,20);end=point([0,120,0,107],214.84003,30)
        unknown=automatic_boundary(before,resume,source_head=3,target_head=1,runout=True,mapping=[0,1,2,1])
        known=automatic_boundary(before,resume,source_head=3,target_head=1,runout=True,mapping=[0,1,2,1],service_heads=(0,20,0,5),service_counter=12.84003,provenance='synthetic_ground_truth')
        check('constant offset and matching later deltas do not prove boundary',abs(unknown['observed_scope_difference_mm']-12.15997)<1e-8 and not unknown['consistent'] and printing_interval(resume,end)['consistent'])
        check('independent synthetic commands explain only this fixture',known['consistent'] and not known['authorizes_debit'])
        # Collector waits for late packets before rejecting the changed mapping/total.
        multi.wait(lambda:owner.call('inspect')['reviews'],timeout=45)
        for _ in range(5):owner.call('history',p.pid,history)
        check('real collector and repeated history authorize no debit',not owner.call('inspect')['debits'] and all(s['remaining_mg']==500000 for s in owner.call('inspect')['spools']))
        generation=fleet.snapshot()[p.pid]['connections'];p.stop_m();multi.wait(lambda:fleet.snapshot()[p.pid]['state']=='offline');p.start_m()
        multi.wait(lambda:fleet.snapshot()[p.pid]['connections']>generation and fleet.snapshot()[p.pid]['state']=='ready')
        for _ in range(3):owner.call('history',p.pid,read_history())
        check('reconnect does not unblock research consumption',not owner.call('inspect')['debits'])
        check('no remote debit queued',not owner.call('library_snapshot')['remote_outbox'])
        (out/'results.json').write_text(json.dumps(dict(checks=checks,scenario=args.scenario,arrival_filtered_mm=naive,ground_truth_service_mm=25,uncertain_partition=uncertain,trace=trace,partition=partition,unproven=unknown,synthetic_only=known,state=owner.call('inspect'),root=str(multi.ROOT)),indent=2))
    finally:
        if worker:worker.stop()
        if owner:owner.close()
        if fleet:fleet.stop()
        if p:
            p.stop_m();p.stop_k();cfg=p.data/'config/printer.cfg';cfg.write_text(cfg.read_text().replace('\n[bench_transition]\n',''));p.close()
            for name in ['klippy','moonraker']:shutil.copy2(p.data/f'logs/{name}.log',out/f'{name}.log')
        if (multi.ROOT/'motion').exists():shutil.copytree(multi.ROOT/'motion',out/'motion',dirs_exist_ok=True)
    (out/'cleanup.json').write_text(json.dumps(dict(stopped=p.k is None and p.m is None,temporary_root=str(multi.ROOT))))
    print(f'{len(checks)} process research checks passed',flush=True)

if __name__=='__main__':main()
