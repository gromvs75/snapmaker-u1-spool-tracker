"""Live UID transport + normalized synthetic print evidence + atomic accounting."""
from pathlib import Path
import sys,json,hashlib,shutil
REPO=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(REPO/'src'),str(REPO/'dev/labs/uid_multi_bench')]
from run import Printer,wait,ROOT
from tracker_uid_client import UidFleet,PrinterEndpoint
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import TrackerUidService,AccountingConflict
RESULTS=[]
def check(name,ok,evidence=None):
    assert ok,name
    RESULTS.append(dict(check=name,passed=True,evidence=evidence));print('PASS '+name,flush=True)

def main():
    printers=[];fleet=cat=None;completed=False
    output=REPO/'output/uid-accounting-bench';output.mkdir(exist_ok=True)
    try:
        a=Printer('a',18731);printers.append(a);b=Printer('b',18732);printers.append(b)
        for p in printers:p.start()
        fleet=UidFleet([PrinterEndpoint('a','U1_1',a.url),PrinterEndpoint('b','U1_2',b.url)],poll_interval=.3,response_timeout=2,reconnect_max=1)
        fleet.start();wait(lambda:all(v['state']=='ready' for v in fleet.snapshot().values()))
        db=ROOT/'accounting.sqlite';db.unlink(missing_ok=True)
        cat=UidCatalog(db);service=TrackerUidService(fleet,cat)
        legacy={'schema_version':5,'language':'ru','spools':{'black-original':{'name':'Black','material':'PLA','remaining_g':500},'orange-original':{'name':'Orange','material':'PLA','remaining_g':300}},'runs':{}}
        original=json.dumps(legacy,sort_keys=True)
        bindings={'black-original':'04112233','orange-original':'04AABBCCDDEEFF'}
        service.accounting.import_legacy_snapshot(legacy,bindings)
        check('explicit legacy fixture imports IDs and balances',cat.spool('04112233')['spool_id']=='black-original')
        a.scan(0,'04112233');b.scan(1,'04AABBCCDDEEFF')
        wait(lambda:sum(r['usable'] for r in service.refresh())==2)
        def event(job,state,seq,totals,source='capture1',start='start1'):
            return dict(job_id=job,started_at=start,state=state,sequence=seq,totals_mg=totals,source=source,basis='executed_gcode')
        def deliver(p,e):
            p.http('/printer/bench_radio/print_event',{'event':e})
            wire=p.http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['print_job']
            return service.handle_event(p.pid,wire)
        sa=event('same-history-id','started',0,{'0':0});sb=event('same-history-id','started',0,{'1':0})
        deliver(a,sa);deliver(b,sb)
        check('two overlapping jobs with same remote ID stay distinct',cat.db.execute("SELECT count(*) FROM uid_jobs WHERE state='active'").fetchone()[0]==2)
        pa=event('same-history-id','active',1,{'0':29464});pb=event('same-history-id','active',1,{'1':1997})
        deliver(a,pa);deliver(b,pb)
        check('progress debits only its own spool',cat.spool('04112233')['remaining_mg']==470536 and cat.spool('04AABBCCDDEEFF')['remaining_mg']==298003)
        check('duplicate progress does not debit again',deliver(a,pa)=='duplicate')
        cancelled=event('same-history-id','cancelled',2,{'0':30000})
        deliver(a,cancelled)
        check('cancel books only remainder beyond previous checkpoint',cat.spool('04112233')['remaining_mg']==470000)
        final=event('same-history-id','completed',2,{'1':20000});deliver(b,final)
        check('other print completes independently',cat.spool('04AABBCCDDEEFF')['remaining_mg']==280000)
        a.clear(0);wait(lambda:fleet.snapshot()['a']['channels']['0']['state']=='absent')
        b.scan(2,'04112233');wait(lambda:fleet.snapshot()['b']['channels']['2']['uid']=='04112233')
        deliver(b,event('second-job','started',0,{'2':0},source='capture2',start='start2'))
        check('transfer uses same spool ID and remaining mass',cat.spool('04112233')['spool_id']=='black-original' and cat.spool('04112233')['remaining_mg']==470000)
        check('late cancelled replay after transfer remains duplicate',deliver(a,cancelled)=='duplicate')
        deliver(b,event('second-job','completed',1,{'2':10000},source='capture2',start='start2'))
        check('new job on new tool debits same physical spool once',cat.spool('04112233')['remaining_mg']==460000)
        # Reload accounting DB and repeat history delivery without reapplying usage.
        cat.close();cat=UidCatalog(db);service=TrackerUidService(fleet,cat)
        check('replayed history after application DB reopen is idempotent',deliver(a,cancelled)=='duplicate' and deliver(b,final)=='duplicate')
        service.accounting.import_legacy_snapshot(legacy,bindings)
        check('retrying import cannot restore an old balance',cat.spool('04112233')['remaining_mg']==460000)
        # Change a loaded spool while a print is active: never redirect its debit.
        deliver(b,event('third-job','started',0,{'2':0},source='capture3',start='start3'))
        b.scan(2,'04123456');wait(lambda:fleet.snapshot()['b']['channels']['2']['uid']=='04123456')
        blocked=False
        try:deliver(b,event('third-job','active',1,{'2':5000},source='capture3',start='start3'))
        except AccountingConflict:blocked=True
        check('mid-job spool replacement blocks automatic extra debit',blocked and cat.spool('04112233')['remaining_mg']==460000)
        check('legacy source fixture unchanged',json.dumps(legacy,sort_keys=True)==original)
        totals=dict(cat.db.execute('SELECT spool_id,sum(delta_mg) FROM uid_debits GROUP BY spool_id').fetchall())
        check('ledger totals match inventory changes',totals=={'black-original':40000,'orange-original':20000},totals)
        completed=True
    finally:
        if fleet:fleet.stop()
        if cat:cat.close()
        for p in printers:p.close()
        (output/'results.json').write_text(json.dumps(dict(completed=completed,checks=RESULTS),indent=2))
        for p in printers:
            for name in ('klippy','moonraker'):
                log=p.data/f'logs/{name}.log'
                if log.exists():shutil.copy2(log,output/f'{p.pid}-{name}.log')
    print(f'{len(RESULTS)} accounting integration checks passed; isolated processes stopped',flush=True)
if __name__=='__main__':main()
