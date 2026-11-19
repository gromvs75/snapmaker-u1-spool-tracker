"""Real local Klippy + Spoolman, public Anycubic pages and synthetic QIDI RF.

Requires the same explicit isolated inputs as bambu_run.py; no printer transport.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from dev.labs.uid_live_bench.bambu_run import spoolman, Fleet, scan
from dev.labs.uid_boot_bench.emergency_off_run import prepare, dispatch, off, mesh
from dev.labs.uid_boot_bench.load_fault_run import klippy, rpc
from dev.labs.uid_boot_bench.model import tool
from dev.labs.uid_boot_bench.optional import CFG
from tracker_uid_runtime import AccountingOwner
from tracker_uid_spoolman import Client
from tracker_rfid import RfidWorker


def remove(root,fleet):
    rpc(root,'bench_radio/clear',channel=0)
    for _ in range(100):
        if fleet.snapshot()['bench']['channels']['0']['state']=='absent':return
        time.sleep(.1)
    raise AssertionError('Removal not observed')


def consume(owner,worker,name,density,grams,number):
    start=owner.call('inventory_snapshot','bench');length=grams/(math.pi*(1.75/2)**2*density/1000)
    stamp=1000.+number*100
    ev=dict(complete=True,continuous=True,capture_id=name,epoch='bench-motion',start=start,terminal_state='completed',
            comparison=dict(matches=True,printer_total_mm=length),feed=dict(valid=True,covered=[True]*4,insertions=[False]*4),
            tags=dict(known=True,unchanged=[True]*4,initial=[None]*4),heads=[dict(head=i,net_mm=length if i==0 else 0) for i in range(4)],
            profile=dict(filename=name+'.gcode',started_at=stamp,mapping=[0,1,2,3],logical_weights=[grams,0,0,0]))
    result=owner.call('start','bench',filename=name+'.gcode',observed_at=stamp+1,capture_id=name,
                      epoch=ev['epoch'],start=start,channels=['0'])
    assert result['status']=='started',result
    owner.call('terminal','bench',ev)
    history=[dict(job_id=name,start_time=stamp,filename=name+'.gcode',status='completed')]
    result=owner.call('history','bench',history)[0];assert result['status']=='applied',result
    assert owner.call('history','bench',history)[0]['status']=='duplicate'
    worker.tick();worker.tick()
    assert all(row['state']=='sent' for row in owner.call('delivery_list'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','klipper','driver','dictionary','spoolman','spoolman-python','research','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report=dict(real_printer_used=False,radio_mcu='simulated',qidi_data='synthetic cards from published code triples',
                anycubic_data='three published raw page dumps; second-side UID is synthetic',
                driver_sha256=hashlib.sha256(args.driver.read_bytes()).hexdigest(),checks=[])
    with tempfile.TemporaryDirectory(prefix='multi-rfid-',dir='/private/tmp') as temp:
        base=Path(temp);root=base/'sim';model=prepare(root,args);assert dispatch(model)['state']=='active'
        for extras in (root/'klipper/klippy/extras',root/'_boot_lower/klipper/klippy/extras'):
            for file in ('bambu_radio.py','multibrand_radio.py'):
                shutil.copyfile(ROOT/'dev/labs/uid_live_bench'/file,extras/file)
        main_cfg=root/tool.MAIN;main_cfg.write_text(main_cfg.read_text().replace('[bench_radio]','[multibrand_radio]'))
        original=main_cfg.read_bytes()
        with (root/CFG).open('a') as stream:stream.write('\nbambu_read_enabled: True\nqidi_read_enabled: True\nanycubic_read_enabled: True\n')
        (root/'bambu-dumps').mkdir();(root/'other-dumps').mkdir()
        bambu=json.loads((args.research/'dump-manifest.json').read_text())[0]
        shutil.copyfile(args.research/'dumps'/bambu['path'],root/'bambu-dumps'/(bambu['uid']+'.bin'))
        # No full public QIDI dump was found: these cards are explicitly synthetic.
        for uid,codes in (('04123456',[2,1,1]),('04765432',[2,1,1]),('04556677',[0x29,0x12,1]),('04445566',[0x7E,0x7E,1])):
            data=bytearray(1024);data[:4]=bytes.fromhex(uid);data[64:67]=bytes(codes)
            for sector in range(16):data[(sector*4+3)*16:(sector*4+3)*16+6]=bytes([255]*6)
            (root/'other-dumps'/(uid+'.bin')).write_bytes(data)
        any_manifest=json.loads((args.research/'third-party-dumps/manifest.json').read_text())
        for entry in any_manifest:
            data=(args.research/'third-party-dumps'/entry['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest()==entry['sha256']
            (root/'other-dumps'/entry['path']).write_bytes(data)
        first_any='5330BDAD950001';second_any='04112233445566'
        data=bytearray((root/'other-dumps'/(first_any+'.bin')).read_bytes());u=bytes.fromhex(second_any)
        data[:3]=u[:3];data[3]=0x88^u[0]^u[1]^u[2];data[4:8]=u[3:];data[8]=u[3]^u[4]^u[5]^u[6]
        (root/'other-dumps'/(second_any+'.bin')).write_bytes(data)
        with spoolman(args,base/'spoolman') as url:
            with klippy(root,False) as info:
                assert info['state']=='ready';saved_mesh=mesh(root);fleet=Fleet(root)
                owner=AccountingOwner(base/'tracker.sqlite',fleet)
                try:
                    config=dict(enabled=True,allow_create=True,send_usage=True,new_spools='nominal',
                        confirmed_new_tags=['qidi:chip:04123456','anycubic:chip:'+first_any],
                        densities={'qidi:02':1.32,'anycubic:AHPLPBK-108':1.23},
                        diameters={'qidi:02':1.75},nominal_weights={'qidi:02':1000})
                    owner.call('save_settings',dict(spoolman_url=url,spoolman_mode='send',rfid=config),owner.call('settings')['revision'])
                    worker=RfidWorker(owner,[url]);q=scan(root,fleet,'04123456')
                    assert q['format']=='qidi' and q['material']=='PLA' and q['color']=='FFFFFF' and q['nominal_weight_g'] is None
                    first=worker.scan('bench','0');consume(owner,worker,'qidi-print',1.32,12.5,1)
                    remove(root,fleet);scan(root,fleet,'04765432')
                    try:worker.scan('bench','0')
                    except ValueError:pass
                    else:raise AssertionError('Unconfirmed second chip duplicated a roll')
                    owner.call('rfid_pair',owner.call('rfid_prepare','bench','0'),first['spool_id'],confirmed=True)
                    assert worker.scan('bench','0')['remaining_mg']==987500
                    report['checks'].append('QIDI default-key AUTH/READ, PLA/white, 12.500g once, confirmed second-side -> 987.500g')
                    remove(root,fleet);a=scan(root,fleet,first_any)
                    assert a['format']=='anycubic' and a['material']=='PLA+' and a['color']=='212721'
                    any_spool=worker.scan('bench','0');consume(owner,worker,'anycubic-print',1.23,7.25,2)
                    remove(root,fleet);scan(root,fleet,second_any)
                    owner.call('rfid_pair',owner.call('rfid_prepare','bench','0'),any_spool['spool_id'],confirmed=True)
                    assert worker.scan('bench','0')['remaining_mg']==992750
                    report['checks'].append('Anycubic page READ, PLA+/color, 7.250g once, confirmed second-side -> 992.750g')
                    owner.close();owner=AccountingOwner(base/'tracker.sqlite',fleet);worker=RfidWorker(owner,[url])
                    for uid,expected in (('04123456',987500),(first_any,992750),('04765432',987500),(second_any,992750)):
                        remove(root,fleet);scan(root,fleet,uid);assert worker.scan('bench','0')['remaining_mg']==expected
                    rows,_=Client(url).request('GET','/spool');assert len(rows)==2
                    report['spools']=[dict(id=r['id'],material=r['filament']['material'],color=r['filament'].get('color_hex'),remaining_g=r['remaining_weight']) for r in rows]
                    report['checks'].append('Restart + interleaved removal/return of all four UIDs: two records, balances preserved')
                    pink=scan(root,fleet,'531394D3720001');asa=scan(root,fleet,'1D72F5610F1080')
                    assert pink['color']=='FEC196' and pink['nozzle_max_c']==210
                    assert asa['color']=='008000' and asa['nozzle_min_c']==240 and asa['nozzle_max_c']==280
                    unknown=scan(root,fleet,'04445566');assert unknown['material'] is None and unknown['color'] is None
                    try:worker.scan('bench','0')
                    except ValueError:pass
                    else:raise AssertionError('Unknown QIDI codes created a spool')
                    for mode in ('page','short_page'):
                        rpc(root,'bench_radio/fault',mode=mode);scan(root,fleet,first_any,metadata=False)
                    rpc(root,'bench_radio/fault',mode='auth');scan(root,fleet,'04123456',metadata=False)
                    rpc(root,'bench_radio/fault',mode='none')
                    report['checks'].append('All three published Anycubic payloads; unknown QIDI, auth failure, failed/short Type 2 page held')
                    radio=rpc(root,'objects/query',objects={'multibrand_radio':None})['status']['multibrand_radio']
                    assert radio['write_commands']==0;report['radio']=radio;report['off']=off(root)
                finally:owner.close()
            assert main_cfg.read_bytes()==original and dispatch(model)['state']=='disabled'
            with klippy(root,False) as info:
                assert info['state']=='ready' and 'tracker_uid' not in rpc(root,'objects/list')['objects'] and mesh(root)==saved_mesh
            report['checks'].append('Independent OFF; next cold boot ready, config and saved mesh preserved')
    report['success']=True;(args.output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
