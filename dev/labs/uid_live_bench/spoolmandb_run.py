"""Offline catalog -> simulated radio -> real Klippy/Spoolman -> UI -> return."""
import argparse
import gzip
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'dev/klipper')]
from dev.labs.uid_boot_bench.u1_trial_run import prepare
from dev.labs.uid_boot_bench.load_fault_run import klippy,rpc
from dev.labs.uid_live_bench.bambu_run import spoolman,Fleet,scan
from dev.labs.uid_live_bench.multibrand_run import remove,consume
from dev.labs.uid_live_bench.all_tag_fixtures import ndef
from dev.labs.uid_live_bench.enrollment_ui import browser_enrollment
from tracker_uid import decode_pages
from tracker_rfid_lookup import resolve_names
from tracker_spoolmandb import DATA,suggest
from tracker_uid_runtime import AccountingOwner
from tracker_uid_spoolman import Client
from tracker_rfid import RfidWorker
from playwright.sync_api import expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('klipper','driver','dictionary','spoolman','spoolman-python','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    for name,value in vars(args).items():setattr(args,name,value.absolute())
    args.output.mkdir(parents=True,exist_ok=False)
    uids=['04032233445501','04032233445502']
    # Build synthetic, documented NDEF data from one actual catalog entry.
    # This proves lookup integration, not that this factory spool uses NDEF.
    rows=json.loads(gzip.decompress((DATA/'filaments.json.gz').read_bytes()))
    for row in rows:
        if row['manufacturer']!='Bambu Lab' or row['material']!='PLA' or row['diameter']!=1.75 or row['weight']!=1000:continue
        payload=json.dumps(dict(brand=row['manufacturer'],material=row['material'],color=row['color_hex'],diameter=row['diameter'],weight=row['weight'])).encode()
        raw=ndef(uids[0],'application/json',payload)
        tag=decode_pages(bytes.fromhex(uids[0]),raw,{'generic-ndef'})
        lookup=suggest(tag,resolve_names(tag,{}))
        if lookup['status']=='suggested':break
    else:raise AssertionError('Need an unambiguous real catalog fixture')
    checks=[]
    with tempfile.TemporaryDirectory(prefix='rfid-db-',dir='/private/tmp') as tmp:
        base=Path(tmp);root=base/'u1';trial=prepare(args,root,multibrand=True)
        for uid in uids:(root/'home/lava/other-dumps'/(uid+'.bin')).write_bytes(ndef(uid,'application/json',payload))
        module=ROOT/'dev/klipper/tracker_uid.py'
        trial.install(trial.plan(module,['generic_ndef']),module)
        with spoolman(args,base/'spoolman') as url,klippy(root,False) as info:
            assert info['state']=='ready'
            fleet=Fleet(root);path=base/'tracker.sqlite';owner=AccountingOwner(path,fleet)
            try:
                owner.call('save_settings',dict(language='ru',spoolman_url=url,spoolman_mode='send',rfid=dict(send_usage=True)),owner.call('settings')['revision'])
                assert scan(root,fleet,uids[0])==tag
                worker=RfidWorker(owner,[url])
                with browser_enrollment(owner,fleet,url,args.output) as ui:
                    page=ui.page;page.locator('#desktop-tags-open').click()
                    expect(page.locator('#desktop-rfid-help')).to_contain_text('SpoolmanDB:')
                    expect(page.locator('#desktop-rfid-density')).to_have_value(str(row['density']))
                    expect(page.locator('#desktop-tag-mass')).to_have_value('')
                    checks.append('actual Web UI offers offline catalog density; no remaining-mass guess')
                    ui.apply('generic-ndef',uids[0],remaining=840.123)
                    first=worker.scan('bench','0');sid=first['spool_id']
                    assert first['remaining_mg']==840123
                    consume(owner,worker,'catalog-print',row['density'],20,1)
                    one=worker.scan('bench','0');assert one['remaining_mg']==820123
                    checks.append('confirmed creation and one 20 g delivery to official Spoolman')
                    remove(root,fleet);scan(root,fleet,uids[1]);ui.apply('generic-ndef',uids[1],sid=sid)
                    assert worker.scan('bench','0')['remaining_mg']==820123
                    checks.append('second physical-side UID bound without a new spool or reset')
                saved=owner.call('backup_package');assert owner.call('validate_backup',package=saved)
                from tracker_uid_session import Session
                restored=Session(base/'restored',allowed_urls=[])
                try:
                    checked=restored.call('validate_backup',package=saved)
                    restored.call('restore_backup',package=saved,expected_revision=checked['current_revision'],confirmed=True)
                    restored_row=restored.call('library_snapshot')['spools'][0]
                    assert restored_row['details']['catalog_match']['product_id']==lookup['candidates'][0]['id']
                    assert restored_row['remaining_mg']==820123 and not restored.connected
                finally:restored.close()
                checks.append('actual backup restore retains catalog provenance/balance and stays disconnected')
            finally:owner.close()
            owner=AccountingOwner(path,fleet)
            try:
                worker=RfidWorker(owner,[url])
                for uid in uids+uids:
                    remove(root,fleet);scan(root,fleet,uid);got=worker.scan('bench','0')
                    assert (got['spool_id'],got['remaining_mg'])==(sid,820123)
                remote,_=Client(url).request('GET','/spool')
                assert len(remote)==1 and abs(remote[0]['remaining_weight']-820.123)<.000001
                checks.append('restart and both UIDs preserve one spool and 820.123 g')
            finally:owner.close()
            trial.disable()
        with klippy(root,False) as info:
            assert info['state']=='ready' and 'tracker_uid' not in rpc(root,'objects/list')['objects']
        trial.rollback()
        checks.append('standalone OFF and rollback preserve a bootable Klippy')
    report=dict(success=True,checks=checks,catalog_product=row,catalog_revision=lookup['revision'],
                real_printer_used=False,rfid='synthetic Generic JSON NDEF from real SpoolmanDB properties',
                klippy='real process, simulated electronics',spoolman='official 0.27.1, loopback, disposable data')
    (args.output/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
