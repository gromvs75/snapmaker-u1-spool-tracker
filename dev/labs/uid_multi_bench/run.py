"""Two real Klipper/Moonraker pairs, isolated RF fixtures, one Tracker UID client."""
from pathlib import Path
import sys, json, time, socket, subprocess, shutil, urllib.request
ROOT=Path('/private/tmp/uid-multi')
SOURCE=Path('/private/tmp/tracker-uid-live')
REPO=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(REPO/'src'),str(REPO/'dev/labs/uid_module_bench')]
from install import Installer, MARKER
from tracker_uid_client import UidFleet, PrinterEndpoint
from tracker_uid_catalog import UidCatalog
RESULTS=[]

def wait(fn,timeout=25):
    until=time.monotonic()+timeout;last=None
    while time.monotonic()<until:
        try:
            v=fn()
            if v:return v
        except Exception as exc:last=exc
        time.sleep(.1)
    raise AssertionError('Timed out: '+str(last))

def check(name,truth,evidence=None):
    assert truth,name
    RESULTS.append(dict(check=name,passed=True,evidence=evidence));print('PASS '+name,flush=True)

def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:p.wait(5)
        except subprocess.TimeoutExpired:p.kill();p.wait(3)

class Printer:
    def __init__(self,pid,port):
        self.pid=pid;self.port=port;self.root=ROOT/pid;self.data=self.root/'printer_data';self.k=None;self.m=None
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            s.bind(('127.0.0.1',port))
        if not self.root.exists():
            self.root.mkdir(parents=True)
            (self.root/'.tracker-uid-simulator.json').write_text(json.dumps(MARKER))
            shutil.copytree(SOURCE/'klipper',self.root/'klipper')
        self.installer=Installer(self.root)
        self.installer.rollback()
        for n in ('config','logs','comms','gcodes'):(self.data/n).mkdir(parents=True,exist_ok=True)
        shutil.copy2(REPO/'dev/labs/uid_live_bench/bench_radio.py',self.root/'klipper/klippy/extras/bench_radio.py')
        shutil.copy2(SOURCE/'mcu.dict',self.root/'mcu.dict')
        (self.data/'config/printer.cfg').write_text('[mcu]\nserial: /no-hardware/uid-bench\n[printer]\nkinematics: none\nmax_velocity: 100\nmax_accel: 1000\n[virtual_sdcard]\npath: '+str(self.data/'gcodes')+'\n[pause_resume]\n[display_status]\n[bench_radio]\n')
        self.before=(self.data/'config/printer.cfg').read_bytes()
        (self.data/'config/moonraker.conf').write_text('[server]\nhost: 127.0.0.1\nport: '+str(port)+'\nklippy_uds_address: '+str(self.data/'comms/klippy.sock')+'\n[file_manager]\nfile_system_observer: none\n[machine]\nprovider: none\n[authorization]\ntrusted_clients:\n  127.0.0.1\n[announcements]\ndev_mode: True\n')
        self.installer.install()
    @property
    def url(self):return f'http://127.0.0.1:{self.port}'
    def http(self,path,body=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=2) as r:return json.load(r)
    def spawn(self,name,args):
        with (self.data/f'logs/{name}-console.log').open('ab') as log:
            return subprocess.Popen(args,stdout=log,stderr=log)
    def start_k(self):
        (self.root/'.klipper-running').write_text('multi bench')
        self.k=self.spawn('klippy',[str(SOURCE/'env/bin/python'),str(self.root/'klipper/klippy/klippy.py'),str(self.data/'config/printer.cfg'),'-a',str(self.data/'comms/klippy.sock'),'-I',str(self.root/'gcode'),'-o',str(self.root/'mcu.output'),'-d',str(self.root/'mcu.dict'),'-l',str(self.data/'logs/klippy.log')])
    def start_m(self):
        self.m=self.spawn('moonraker',[str(SOURCE/'env/bin/moonraker'),'-d',str(self.data),'-c',str(self.data/'config/moonraker.conf'),'-l',str(self.data/'logs/moonraker.log')])
    def start(self):self.start_k();self.start_m()
    def stop_m(self):stop(self.m);self.m=None
    def stop_k(self):
        stop(self.k);self.k=None;(self.root/'.klipper-running').unlink(missing_ok=True)
    def close(self):
        self.stop_m();self.stop_k();self.installer.rollback()
        assert (self.data/'config/printer.cfg').read_bytes()==self.before
    def scan(self,ch,uid):
        wait(lambda:self.http('/printer/bench_radio/set_tag',dict(channel=ch,uid=uid)))
        self.http('/printer/bench_radio/scan',dict(channel=ch))
    def clear(self,ch):self.http('/printer/bench_radio/clear',dict(channel=ch))


def main():
    printers=[];fleet=cat=None;completed=False
    output=REPO/'output/uid-multi-bench';output.mkdir(exist_ok=True)
    try:
        a=Printer('a',18731);printers.append(a)
        b=Printer('b',18732);printers.append(b)
        fleet=UidFleet([PrinterEndpoint('a','U1_1',a.url),PrinterEndpoint('b','U1_2',b.url)],poll_interval=.3,response_timeout=2,reconnect_max=1)
        fleet.start()
        wait(lambda:all(s['state']=='offline' for s in fleet.snapshot().values()))
        check('client starts before printers and retries',True)
        for p in printers:p.start()
        wait(lambda:all(s['state']=='ready' for s in fleet.snapshot().values()))
        check('two independent Klipper/Moonraker connections',True,fleet.snapshot())
        # Temporary database only, never the installed Tracker inventory.
        db=ROOT/'catalog.sqlite'
        if db.exists():db.unlink()
        cat=UidCatalog(db)
        red=cat.register('04112233','Red fixture',500000)
        green=cat.register('04AABBCCDDEEFF','Green fixture',321000)
        def rows():return cat.reconcile(fleet.snapshot())
        def at(pid,ch):return next((r for r in rows() if r['printer_id']==pid and r['channel']==str(ch)),None)
        a.scan(0,red['uid']);b.scan(1,green['uid'])
        wait(lambda:(r:=at('a',0)) and r['usable']);wait(lambda:(r:=at('b',1)) and r['usable'])
        check('simultaneous scans keep printers and channels separate',at('a',0)['spool']==red and at('b',1)['spool']==green)
        a.clear(0);wait(lambda:at('a',0) is None)
        b.scan(2,red['uid']);wait(lambda:(r:=at('b',2)) and r['usable'])
        check('spool moves A:T0 to B:T2 with same ID and balance',at('b',2)['spool']==red)
        a.scan(3,red['uid'])
        wait(lambda:len([r for r in rows() if r['state']=='conflict'])==2)
        check('duplicate UID blocks both locations',all(not r['usable'] for r in rows() if r['uid']==red['uid']))
        a.clear(3);wait(lambda:(r:=at('b',2)) and r['usable'])
        check('confirmed removal resolves duplicate',at('a',3) is None)
        # Make A own red again, then lose A while B observes that UID.
        b.clear(2);wait(lambda:at('b',2) is None)
        a.scan(0,red['uid']);wait(lambda:(r:=at('a',0)) and r['usable'])
        before=fleet.snapshot()['a']['connections'];a.stop_m()
        wait(lambda:fleet.snapshot()['a']['state']=='offline')
        check('Moonraker loss invalidates live UID',fleet.snapshot()['a']['channels']['0']['uid'] is None)
        check('other printer remains usable',at('b',1)['usable'])
        b.scan(2,red['uid']);wait(lambda:len([r for r in rows() if r['state']=='conflict'])==2)
        check('offline previous holder prevents unsafe reassignment',all(not r['usable'] for r in rows() if r['uid']==red['uid']))
        a.start_m();wait(lambda:fleet.snapshot()['a']['state']=='ready' and fleet.snapshot()['a']['connections']>before)
        a.clear(0);wait(lambda:(r:=at('b',2)) and r['usable'])
        check('reconnect resubscribes and confirmed removal allows transfer',at('b',2)['spool']==red)
        epoch=fleet.snapshot()['b']['epoch']
        b.http('/printer/restart',{})
        wait(lambda:fleet.snapshot()['b']['state']=='ready' and fleet.snapshot()['b']['epoch']!=epoch)
        check('Klipper restart replaces epoch and clears live channels',all(c['uid'] is None for c in fleet.snapshot()['b']['channels'].values()))
        check('persisted assignments now uncertain',all(not r['usable'] for r in rows() if r['printer_id']=='b'))
        b.scan(2,red['uid']);wait(lambda:(r:=at('b',2)) and r['usable'])
        check('rescan after restart recovers same spool',at('b',2)['spool']==red)
        # Stop/restart the client itself, preserving catalog balances/uncertain claims.
        rows();fleet.stop();cat.close();cat=UidCatalog(db)
        check('catalog survives client restart',cat.spool(red['uid'])==red and all(not r['usable'] for r in cat.reconcile({})))
        fleet.start();wait(lambda:all(s['state']=='ready' for s in fleet.snapshot().values()))
        wait(lambda:(r:=at('b',2)) and r['usable'])
        check('client restart restores subscriptions and identity',at('b',2)['spool']==red)
        b.clear(2);wait(lambda:at('b',2) is None)
        a.scan(1,red['uid']);wait(lambda:(r:=at('a',1)) and r['usable'])
        check('return to different head on first printer preserves balance',at('a',1)['spool']==red)
        # API disappears while the printer remains usable, then is reinstalled.
        a.stop_k();a.installer.rollback();a.start_k()
        wait(lambda:a.http('/printer/info')['result']['state']=='ready')
        wait(lambda:fleet.snapshot()['a']['state']!='ready')
        check('missing module does not leave a stale ready snapshot',fleet.snapshot()['a']['channels']['1']['uid'] is None)
        a.stop_k();a.installer.install();a.start_k()
        wait(lambda:fleet.snapshot()['a']['state']=='ready')
        a.scan(1,red['uid']);wait(lambda:(r:=at('a',1)) and r['usable'])
        check('client discovers reinstalled module without manual restart',at('a',1)['spool']==red)
        check('client receives push notifications on both printers',all(s['push_notifications']>0 for s in fleet.snapshot().values()),fleet.snapshot())
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
    print(f'{len(RESULTS)} integration checks passed; processes stopped, modules rolled back',flush=True)
if __name__=='__main__':main()
