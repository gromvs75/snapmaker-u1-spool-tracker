"""Real Klippy + stock driver + official Spoolman; synthetic RF/MCU/consumption.

All paths explicit; Spoolman binds loopback in a fresh temporary data directory.
No printer network transport is instantiated. Public dumps remain output data.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from dev.labs.uid_boot_bench.emergency_off_run import prepare, dispatch, off, mesh
from dev.labs.uid_boot_bench.load_fault_run import klippy, rpc
from dev.labs.uid_boot_bench.model import tool
from dev.labs.uid_boot_bench.optional import CFG
from tracker_uid_client import validate_status
from tracker_uid_runtime import AccountingOwner
from tracker_uid_spoolman import Client
from tracker_rfid import RfidWorker


@contextmanager
def spoolman(args, work):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    frontend=args.spoolman/'client_v2/build';frontend.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PATH=str(args.spoolman_python.parent)+os.pathsep+os.environ['PATH'],
             SPOOLMAN_DIR_DATA=str(work/'data'),SPOOLMAN_DIR_LOGS=str(work/'logs'),
             SPOOLMAN_DIR_BACKUPS=str(work/'backups'),SPOOLMAN_UPDATE_CHECK='FALSE',
             SPOOLMAN_AUTOMATIC_BACKUP='FALSE',EXTERNAL_DB_URL='',EXTERNAL_DB_SYNC_INTERVAL='0')
    with (args.output/'spoolman.log').open('wb') as log:
        process=subprocess.Popen([str(args.spoolman_python),'-m','uvicorn','spoolman.main:app',
                                  '--host','127.0.0.1','--port',str(port)],cwd=args.spoolman,env=env,stdout=log,stderr=log)
        url='http://127.0.0.1:'+str(port)
        try:
            for _ in range(150):
                if process.poll() is not None:raise RuntimeError((args.output/'spoolman.log').read_text()[-2500:])
                try:
                    info,_=Client(url).request('GET','/info')
                    if info['version']=='0.27.1':break
                except Exception:pass
                time.sleep(.1)
            else:raise TimeoutError('Spoolman startup')
            yield url
        finally:
            process.terminate()
            try:process.wait(10)
            except subprocess.TimeoutExpired:process.kill();process.wait()


class Fleet:
    def __init__(self, root):self.root=root
    def snapshot(self):
        s=rpc(self.root,'objects/query',objects={'tracker_uid':None,'print_stats':None,'webhooks':None})['status']
        uid=validate_status(s['tracker_uid'])
        return {'bench':dict(uid,printer_id='bench',client_session='bench-session',generation=1,
                             printer_connected=s['webhooks']['state']=='ready',print_state=s['print_stats']['state'])}


def scan(root, fleet, uid, metadata=True):
    before=fleet.snapshot()['bench']['sequence']
    rpc(root,'bench_radio/set_tag',channel=0,uid=uid)
    rpc(root,'bench_radio/scan',channel=0)
    for _ in range(150):
        s=fleet.snapshot()['bench'];c=s['channels']['0']
        if s['sequence']>before and c.get('uid')==uid:
            if metadata and c.get('tag',{}).get('uid')==uid:return c['tag']
            if not metadata:
                assert c.get('tag') is None
                return c
        time.sleep(.1)
    raise AssertionError('Bambu RF scan failed: '+repr(s))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','klipper','driver','dictionary','spoolman','spoolman-python','research','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((args.research/'dump-manifest.json').read_text())
    selected=['0DF58A36','9D1A8636','0231BF32','053A74A4']
    report=dict(real_printer_used=False,spoolman_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.spoolman,text=True).strip(),
                driver_sha256=hashlib.sha256(args.driver.read_bytes()).hexdigest(),
                rf_gpio_spi_mcu='simulated',consumption='synthetic motion/history -> real allocator, UID ledger and automatic sender: 12.500 g',
                transport='Klippy Unix socket, full status validated by Tracker; no Moonraker process',checks=[])
    with tempfile.TemporaryDirectory(prefix='bambu-bench-',dir='/private/tmp') as temp:
        base=Path(temp);root=base/'sim';model=prepare(root,args)
        assert dispatch(model)['state']=='active'
        for extras in (root/'klipper/klippy/extras',root/'_boot_lower/klipper/klippy/extras'):
            shutil.copyfile(ROOT/'dev/labs/uid_live_bench/bambu_radio.py',extras/'bambu_radio.py')
        main_cfg=root/tool.MAIN
        main_cfg.write_text(main_cfg.read_text().replace('[bench_radio]','[bambu_radio]'))
        original=main_cfg.read_bytes()
        with (root/CFG).open('a') as cfg:cfg.write('\nbambu_read_enabled: True\n')
        (root/'bambu-dumps').mkdir()
        for uid in selected:
            row=next(r for r in manifest if r['uid']==uid)
            shutil.copyfile(args.research/'dumps'/row['path'],root/'bambu-dumps'/f'{uid}.bin')
        with spoolman(args,base/'spoolman') as url:
            with klippy(root,False) as info:
                assert info['state']=='ready'
                saved_mesh=mesh(root);fleet=Fleet(root)
                owner=AccountingOwner(base/'tracker.sqlite',fleet)
                try:
                    owner.call('save_settings',dict(spoolman_url=url,spoolman_mode='send',rfid=dict(
                        enabled=True,allow_create=True,send_usage=True,new_spools='nominal',densities={'GFA00':1.24,'GFA05':1.32,'GFG00':1.25})),
                        owner.call('settings')['revision'])
                    worker=RfidWorker(owner,[url])
                    for fault in ('auth','identity_block'):
                        rpc(root,'bench_radio/fault',mode=fault)
                        scan(root,fleet,selected[0],metadata=False)
                        try:worker.scan('bench','0')
                        except ValueError:pass
                        else:raise AssertionError('Partial metadata enrolled a spool')
                        rows,_=Client(url).request('GET','/spool');assert not rows
                    rpc(root,'bench_radio/fault',mode='none')
                    report['checks'].append('AUTH failure and unreadable roll-ID block: UID only, no Spoolman creation')
                    tag=scan(root,fleet,selected[0]);first=worker.scan('bench','0')
                    assert tag['material']=='PLA' and tag['color']=='C12E1F' and first['remaining_mg']==1000000
                    report['checks'].append('Public Bambu dump AUTH/READ through stock methods; material/color -> Spoolman')
                    start=owner.call('inventory_snapshot','bench')
                    length=12.5/(math.pi*(1.75/2)**2*1.24/1000)
                    evidence=dict(complete=True,continuous=True,capture_id='synthetic-motion',epoch='bench-motion',
                        start=start,terminal_state='completed',comparison=dict(matches=True,printer_total_mm=length),
                        feed=dict(valid=True,covered=[True]*4,insertions=[False]*4),
                        tags=dict(known=True,unchanged=[True]*4,initial=[None]*4),
                        heads=[dict(head=i,net_mm=length if i==0 else 0) for i in range(4)],
                        profile=dict(filename='synthetic.gcode',started_at=1010.,mapping=[0,1,2,3],
                                     logical_weights=[12.5,0,0,0],filament_type='PLA;PLA;PLA;PLA',
                                     parameters=[dict(diameter_mm=1.75,density_g_cm3=1.24)]*4))
                    started=owner.call('start','bench',filename='synthetic.gcode',observed_at=1011.,
                        capture_id=evidence['capture_id'],epoch=evidence['epoch'],start=start,channels=['0'])
                    assert started['status']=='started',started
                    owner.call('terminal','bench',evidence)
                    history=[dict(job_id='synthetic-print',start_time=1010.,filename='synthetic.gcode',status='completed')]
                    applied=owner.call('history','bench',history)[0]
                    assert applied['status']=='applied',applied
                    assert owner.call('history','bench',history)[0]['status']=='duplicate'
                    worker.tick();worker.tick()
                    assert owner.call('delivery_list')[0]['state']=='sent'
                    remote,_=Client(url).request('GET','/spool/1');assert remote['remaining_weight']==987.5
                    report['checks'].append('Synthetic motion -> 12.500 g once; opt-in automatic sender -> real Spoolman once')
                    owner.close();owner=AccountingOwner(base/'tracker.sqlite',fleet);worker=RfidWorker(owner,[url])
                    rpc(root,'bench_radio/clear',channel=0)
                    for _ in range(100):
                        if fleet.snapshot()['bench']['channels']['0']['state']=='absent':break
                        time.sleep(.1)
                    else:raise AssertionError('Removal not observed')
                    scan(root,fleet,selected[2]);other=worker.scan('bench','0')
                    assert other['spool_id']!=first['spool_id']
                    scan(root,fleet,selected[1]);again=worker.scan('bench','0')
                    assert again['spool_id']==first['spool_id'] and again['remaining_mg']==987500
                    assert len(owner.call('inspect')['spools'])==2
                    report['checks'].append('Remove, mount PETG, return PLA opposite-side UID: same spool and 987.500 g')
                    scan(root,fleet,selected[3]);silk=worker.scan('bench','0')
                    rows,_=Client(url).request('GET','/spool')
                    assert len(rows)==3
                    report['spoolman_spools']=[dict(id=r['id'],material=r['filament']['material'],
                        color=r['filament'].get('color_hex'),colors=r['filament'].get('multi_color_hexes'),remaining_g=r['remaining_weight']) for r in rows]
                    assert any(r['filament'].get('multi_color_hexes')=='7F3696,006EC9' for r in rows)
                    report['checks'].append('Two-colour PLA Silk preserved in Spoolman')
                    radio=rpc(root,'objects/query',objects={'bambu_radio':None})['status']['bambu_radio']
                    assert radio['write_commands']==0 and radio['rf_commands']>0
                    report['radio']=radio
                    report['same_roll']=[first,again]
                    report['off']=off(root)
                finally:owner.close()
            assert main_cfg.read_bytes()==original
            assert dispatch(model)['state']=='disabled'
            with klippy(root,False) as info:
                assert info['state']=='ready'
                assert 'tracker_uid' not in rpc(root,'objects/list')['objects']
                assert mesh(root)==saved_mesh
            report['checks'].append('Independent OFF; next cold boot ready without RFID, config and mesh preserved')
        shutil.copyfile(root/'process.log',args.output/'klippy-off.log')
    report['success']=True
    (args.output/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
