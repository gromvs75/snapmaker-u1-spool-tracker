"""Real isolated Klippy + Spoolman, simulated AUTH/READ for all added formats."""
from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'dev/klipper')]
from dev.labs.uid_live_bench.bambu_run import spoolman,Fleet,scan
from dev.labs.uid_live_bench.multibrand_run import remove,consume
from dev.labs.uid_live_bench.all_tag_fixtures import KINDS,MASTER,PAYLOAD_KEY,fixture,uid_for,ndef
from dev.labs.uid_boot_bench.emergency_off_run import prepare,dispatch,off,mesh
from dev.labs.uid_boot_bench.load_fault_run import klippy,rpc
from dev.labs.uid_boot_bench.model import tool
from dev.labs.uid_boot_bench.optional import CFG
from tracker_uid_runtime import AccountingOwner
from tracker_uid_spoolman import Client
from tracker_rfid import RfidWorker
from tracker_uid import decode_creality,decode_pages,aes128


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','klipper','driver','dictionary','spoolman','spoolman-python','research','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--automatic',action='store_true',help='Public Creality keys + offline TigerTag names, without manual lookup')
    parser.add_argument('--enrollment-ui',action='store_true')
    args=parser.parse_args()
    for name,value in vars(args).items():
        if isinstance(value,Path):setattr(args,name,value.absolute())
    make_fixture,payload_key=fixture,PAYLOAD_KEY
    if args.automatic:
        from dev.labs.uid_live_bench.automatic_tag_fixtures import fixture as make_fixture, PAYLOAD_KEY as payload_key
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(real_printer_used=False,radio_mcu='simulated',archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                driver_sha256=hashlib.sha256(args.driver.read_bytes()).hexdigest(),cases=[],checks=[])
    with tempfile.TemporaryDirectory(prefix='all-rfid-',dir='/private/tmp') as temp:
        base=Path(temp);root=base/'sim';model=prepare(root,args);assert dispatch(model)['state']=='active'
        for extras in (root/'klipper/klippy/extras',root/'_boot_lower/klipper/klippy/extras'):
            for file in ('bambu_radio.py','multibrand_radio.py'):
                shutil.copyfile(ROOT/'dev/labs/uid_live_bench'/file,extras/file)
        main_cfg=root/tool.MAIN;main_cfg.write_text(main_cfg.read_text().replace('[bench_radio]','[multibrand_radio]'))
        original=main_cfg.read_bytes()
        with (root/CFG).open('a') as stream:
            for name in ('bambu','qidi','anycubic')+KINDS:stream.write('\n'+name.replace('-','_')+'_read_enabled: True\n')
            if not args.automatic:
                stream.write('\ncreality_master_key: '+MASTER+'\ncreality_payload_key: '+PAYLOAD_KEY+'\n')
        (root/'bambu-dumps').mkdir();(root/'other-dumps').mkdir()
        bambu=json.loads((args.research/'dump-manifest.json').read_text())[0]
        shutil.copyfile(args.research/'dumps'/bambu['path'],root/'bambu-dumps'/(bambu['uid']+'.bin'))
        cases=[]
        for kind in KINDS:
            for side in (0,1):(root/'other-dumps'/(uid_for(kind,side)+'.bin')).write_bytes(make_fixture(kind,side))
            cases.append((kind,uid_for(kind),uid_for(kind,1),'synthetic documented-layout RF'))
        public=args.research/'all-format-dumps'
        for row in json.loads((public/'manifest.json').read_text()):
            assert hashlib.sha256((public/row['path']).read_bytes()).hexdigest()==row['sha256']
        uid='53CD8309300004';shutil.copyfile(public/(uid+'.bin'),root/'other-dumps'/(uid+'.bin'))
        cases.append(('elegoo',uid,None,'published factory raw-page dump'))
        uid='04002233445566';(root/'other-dumps'/(uid+'.bin')).write_bytes(ndef(uid,'application/vnd.openprinttag',(public/'prusament.cbor').read_bytes()))
        cases.append(('openprinttag',uid,None,'published Prusament CBOR on synthetic Type 2 carrier; NOT ISO15693'))
        tags=[]
        for kind,uid,_,_ in cases:
            raw=(root/'other-dumps'/(uid+'.bin')).read_bytes();u=bytes.fromhex(uid)
            tags.append(decode_creality(u,aes128(bytes.fromhex(payload_key),raw[64:112],True)) if kind=='creality' else decode_pages(u,raw,set(KINDS)))
        with spoolman(args,base/'spoolman') as url, ExitStack() as stack:
            with klippy(root,False) as info:
                assert info['state']=='ready';saved_mesh=mesh(root);fleet=Fleet(root);owner=AccountingOwner(base/'tracker.sqlite',fleet)
                try:
                    # 1.24 is an explicit synthetic bench calibration, not a claim about each real product.
                    cfg=dict(enabled=True,allow_create=True,send_usage=True,new_spools='nominal',
                        confirmed_new_tags=[t['identity'] for t in tags],densities={t['material_id']:1.24 for t in tags},
                        diameters={t['material_id']:1.75 for t in tags},nominal_weights={t['material_id']:1000 for t in tags},
                        material_names={t['material_id']:'PLA' for t in tags if t['format']=='tigertag'},
                        manufacturer_names={t['material_id']:'Bench filament' for t in tags if t['format']=='tigertag'})
                    if args.automatic:
                        cfg.pop('material_names');cfg.pop('manufacturer_names')
                    if args.enrollment_ui:cfg.update(enabled=False,allow_create=False,new_spools='hold',confirmed_new_tags=[])
                    owner.call('save_settings',dict(language='ru',spoolman_url=url,spoolman_mode='send',rfid=cfg),owner.call('settings')['revision'])
                    report['automatic_lookup']=args.automatic
                    worker=RfidWorker(owner,[url]);returns=[]
                    ui=None
                    if args.enrollment_ui:
                        from dev.labs.uid_live_bench.enrollment_ui import browser_enrollment
                        ui=stack.enter_context(browser_enrollment(owner,fleet,url,args.output))
                    for i,((kind,uid,other,evidence),expected) in enumerate(zip(cases,tags),1):
                        remove(root,fleet);observed=scan(root,fleet,uid)
                        assert observed==expected,(observed,expected)
                        if ui:ui.apply(kind,uid)
                        one=worker.scan('bench','0');grams=i+1.25;balance=1000000-round(grams*1000)
                        consume(owner,worker,'all-format-'+str(i),1.24,grams,i)
                        returns.append((uid,one['spool_id'],balance))
                        if other:
                            remove(root,fleet);scan(root,fleet,other)
                            try:worker.scan('bench','0')
                            except ValueError:pass
                            else:raise AssertionError('Unconfirmed second side created another spool')
                            if ui:ui.apply(kind,other,sid=one['spool_id'])
                            else:owner.call('rfid_pair',owner.call('rfid_prepare','bench','0'),one['spool_id'],confirmed=True)
                            assert worker.scan('bench','0')['remaining_mg']==balance
                            returns.append((other,one['spool_id'],balance))
                        report['cases'].append(dict(format=kind,source=evidence,material=expected['material'],color=expected['color'],
                            resolved_material='PLA' if kind=='tigertag' else expected['material'],used_g=grams,remaining_g=balance/1000.,
                            second_side_paired=bool(other),spool_id=one['spool_id']))
                    stack.close()
                    report['enrollment_ui']=bool(ui)
                    owner.close();owner=AccountingOwner(base/'tracker.sqlite',fleet);worker=RfidWorker(owner,[url])
                    for uid,sid,balance in reversed(returns):
                        remove(root,fleet);scan(root,fleet,uid);restored=worker.scan('bench','0')
                        assert restored['spool_id']==sid and restored['remaining_mg']==balance
                    rows,_=Client(url).request('GET','/spool');assert len(rows)==len(cases)
                    library={r['spool_id']:r for r in owner.call('library_snapshot')['spools']}
                    for case in report['cases']:
                        assert library[case['spool_id']]['details']['material']==case['resolved_material']
                        assert library[case['spool_id']]['details']['diameter']==1.75
                        if args.automatic and case['format']=='tigertag':
                            details=library[case['spool_id']]['details']
                            assert details['manufacturer']=='Bambu Lab' and details['lookup_sources']
                            report['tigertag_lookup']=details['lookup_sources']
                    for row,case in zip(sorted(rows,key=lambda r:r['id']),report['cases']):
                        assert row['filament']['material']==case['resolved_material']
                        assert row['filament']['color_hex'].upper()==case['color']
                        assert abs(row['remaining_weight']-case['remaining_g'])<.0001
                    report['spoolman_rows']=[dict(id=r['id'],material=r['filament']['material'],
                        color=r['filament']['color_hex'],remaining_g=r['remaining_weight']) for r in rows]
                    report['checks'].append('Eight flows: AUTH/READ -> material/color -> real Spoolman -> motion ledger -> usage exactly once')
                    report['checks'].append('Six confirmed second-side aliases; restart and all fourteen UID returns preserve eight balances')
                    for mode,uid in [('auth',uid_for('creality')),('page',uid_for('elegoo')),('short_page',uid_for('opentag'))]:
                        rpc(root,'bench_radio/fault',mode=mode);scan(root,fleet,uid,metadata=False)
                    rpc(root,'bench_radio/fault',mode='none')
                    radio=rpc(root,'objects/query',objects={'multibrand_radio':None})['status']['multibrand_radio'];assert radio['write_commands']==0
                    report['radio']=radio;report['checks'].append('AUTH failure, failed/short Type 2 read: UID-only, no metadata')
                    report['off']=off(root)
                finally:
                    stack.close();owner.close()
                    shutil.copyfile(root/'process.log',args.output/'klippy-process.log')
            assert main_cfg.read_bytes()==original and dispatch(model)['state']=='disabled'
            with klippy(root,False) as info:
                assert info['state']=='ready' and 'tracker_uid' not in rpc(root,'objects/list')['objects'] and mesh(root)==saved_mesh
            report['checks'].append('Independent OFF -> cold boot ready; config and mesh preserved')
    report['success']=True;(args.output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
