"""Common physical-roll IDs through real Klippy/Spoolman, simulated electronics.

No GUI process, printer transport or user data. Every service uses a temporary
directory and loopback/Unix sockets and is stopped by its context manager.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from dev.labs.uid_boot_bench.u1_trial_run import prepare
from dev.labs.uid_boot_bench.load_fault_run import klippy, rpc
from dev.labs.uid_live_bench.bambu_run import spoolman, Fleet, scan
from dev.labs.uid_live_bench.multibrand_run import remove, consume
from dev.labs.uid_live_bench.roll_identity_fixtures import pages, INSTANCE
from tracker_rfid import RfidWorker
from tracker_rfid_enrollment import Enrollment
from tracker_rfid_metadata import roll_key
from tracker_uid_runtime import AccountingOwner
from tracker_uid_spoolman import Client
from tracker_uid_sender import Sender
from tracker_uid_session import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('klipper','driver','dictionary','spoolman','spoolman-python','research','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items(): setattr(args, name, value.absolute())
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.research/'dump-manifest.json').read_text())
    cases = [('bambu', ['0DF58A36','9D1A8636','05612205']),
             ('openprinttag', ['04052233445501','04052233445502','04052233445503'])]
    checks = [];results = [];bindings = []
    with tempfile.TemporaryDirectory(prefix='roll-id-', dir='/private/tmp') as tmp:
        base = Path(tmp);root = base/'u1';trial = prepare(args, root, multibrand=True)
        for uid in cases[0][1]:
            row = next(r for r in manifest if r['uid']==uid)
            raw = (args.research/'dumps'/row['path']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==row['sha256']
            (root/'home/lava/bambu-dumps'/(uid+'.bin')).write_bytes(raw)
        for n, uid in enumerate(cases[1][1]):
            instance = INSTANCE if n<2 else bytes.fromhex('12346F54D4754C33A89C15C14AFA9D11')
            (root/'home/lava/other-dumps'/(uid+'.bin')).write_bytes(pages(uid, instance))
        module = ROOT/'dev/klipper/tracker_uid.py'
        trial.install(trial.plan(module, ['bambu','openprinttag']), module)
        with spoolman(args, base/'spoolman') as url, klippy(root, False) as info:
            assert info['state']=='ready'
            fleet = Fleet(root);path = base/'tracker.sqlite';owner = AccountingOwner(path, fleet)
            try:
                owner.call('save_settings', dict(language='ru', spoolman_url=url, spoolman_mode='send',
                                                 rfid=dict(send_usage=True)), owner.call('settings')['revision'])
                worker = RfidWorker(owner, [url], interactive=True)
                service = Enrollment(owner, fleet, lambda pid:'standby', Sender(owner, [url]))
                for number, (kind, uids) in enumerate(cases, 1):
                    remove(root, fleet);a = scan(root, fleet, uids[0])
                    try: worker.scan('bench', '0')
                    except ValueError: pass
                    else: raise AssertionError('New physical roll skipped confirmation')
                    review = service.preview('bench', '0', uids[0])
                    first = service.confirm(review['review_id'], 'new', confirmed=True,
                                            values=dict(remaining_g=840.123,density=1.24,diameter=1.75,nominal=1000))
                    consume(owner, worker, kind+'-identity-print', 1.24, 20, number)
                    remove(root, fleet);b = scan(root, fleet, uids[1]);second = worker.scan('bench','0')
                    assert roll_key(a)==roll_key(b) and a['uid']!=b['uid']
                    assert (second['spool_id'],second['remaining_mg'])==(first['spool_id'],820123)
                    remote, _ = Client(url).request('GET','/spool')
                    assert len(remote)==number*2-1
                    checks.append(kind+': first confirmation, debit once, opposite UID automatically restores 820.123 g')
                    bindings.extend((uid, first['spool_id']) for uid in uids[:2])
                    remove(root, fleet);different = scan(root,fleet,uids[2])
                    assert roll_key(different)!=roll_key(a)
                    assert (different['material'],different['color'])==(a['material'],a['color'])
                    try: worker.scan('bench','0')
                    except ValueError: pass
                    else: raise AssertionError('Different physical roll was merged')
                    review = service.preview('bench','0',uids[2])
                    third = service.confirm(review['review_id'],'new',confirmed=True,
                                            values=dict(remaining_g=840.123,density=1.24,diameter=1.75,nominal=1000))
                    assert third['spool_id']!=first['spool_id']
                    results.append(dict(format=kind,first_uid=a['uid'],second_uid=b['uid'],shared_id=roll_key(a),
                                        material=a['material'],color=a['color'],remaining_g=820.123,
                                        same_product_different_instance_kept_separate=True))
                saved = owner.call('backup_package')
            finally: owner.close()
            owner = AccountingOwner(path, fleet)
            try:
                worker = RfidWorker(owner,[url],interactive=True)
                for uid, sid in bindings:
                    remove(root,fleet);scan(root,fleet,uid);got = worker.scan('bench','0')
                    assert (got['spool_id'],got['remaining_mg'])==(sid,820123)
                checks.append('process restart and all four side UIDs retain the correct balances')
                remote,_ = Client(url).request('GET','/spool')
                assert len(remote)==4
                assert sorted(round(r['remaining_weight'],3) for r in remote)==[820.123,820.123,840.123,840.123]
                assert len(owner.call('delivery_list'))==2
                radio = rpc(root,'objects/query',objects={'multibrand_radio':None})['status']['multibrand_radio']
                assert radio['rf_commands']>0 and radio['write_commands']==0
            finally: owner.close()
            restored = Session(base/'restored',allowed_urls=[])
            try:
                checked = restored.call('validate_backup',package=saved)
                restored.call('restore_backup',package=saved,expected_revision=checked['current_revision'],confirmed=True)
                rows = restored.call('library_snapshot')['spools']
                assert sorted(r['remaining_mg'] for r in rows)==[820123,820123,840123,840123]
                assert not restored.connected
            finally: restored.close()
            checks.append('backup actually restored balances into a fresh disconnected profile')
            trial.disable()
        with klippy(root,False) as info:
            assert info['state']=='ready' and 'tracker_uid' not in rpc(root,'objects/list')['objects']
        trial.rollback();checks.append('OFF then real Klippy ready without RFID; rollback completed')
    report = dict(success=True,real_printer_used=False,checks=checks,cases=results,radio=radio,
                  source='Bambu: public paired dumps; OpenPrintTag: synthetic instance UUID on Type 2 tags',
                  klippy='real process; simulated RF/SPI/GPIO/MCU',spoolman='official 0.27.1; loopback disposable data',
                  module_sha256=hashlib.sha256(module.read_bytes()).hexdigest())
    (args.output/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
