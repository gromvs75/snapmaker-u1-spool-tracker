"""ZIP module -> real Klippy -> loopback bridge -> delivered Mac rc2 binary.

RF/MCU are simulated. Official Spoolman and packaged app use disposable profiles.
No native GUI assertions: this verifies the actual packaged backend/protocol.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from dev.labs.uid_boot_bench.u1_trial_run import prepare
from dev.labs.uid_boot_bench.load_fault_run import klippy, rpc
from dev.labs.uid_live_bench.bambu_run import spoolman, Fleet, scan
from dev.labs.uid_live_bench.multibrand_run import remove
from dev.labs.uid_candidate_bench.run import wait
from tracker_uid_spoolman import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive','exe','klipper','driver','dictionary','spoolman','spoolman-python','research','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items(): setattr(args, name, value.absolute())
    args.output.mkdir(parents=True, exist_ok=False)
    build = json.loads((args.exe.parent.parent/'Resources/tracker_build.json').read_text())
    assert build == dict(build, commit='01cfe7b7503dac3f6b2df4d0c69813e54cac4dd3', dirty=False)
    checks = []; app = sim = None; descriptor = {}
    with tempfile.TemporaryDirectory(prefix='rfid-archive-app-', dir='/private/tmp') as tmp, (args.output/'process.log').open('w') as log:
        base = Path(tmp); root = base/'u1'; profile = base/'profile'; wire = base/'reader.json'
        trial = prepare(args, root, multibrand=True)
        distribution = base/'distribution'; distribution.mkdir()
        with ZipFile(args.archive) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            for name, digest in manifest['files'].items():
                assert Path(name).name == name
                raw = bundle.read(name); assert hashlib.sha256(raw).hexdigest() == digest
                (distribution/name).write_bytes(raw)
        command = [sys.executable, '-I', str(distribution/'rfid_u1_trial.py')]
        tail = ['--offline-root',str(root),'--module',str(distribution/'tracker_uid.py')]
        plan = subprocess.run(command+['plan']+tail+['--formats','bambu'], check=True, capture_output=True, text=True)
        (base/'plan.json').write_text(plan.stdout)
        subprocess.run(command+['install']+tail+['--plan',str(base/'plan.json')], check=True, capture_output=True)
        dumps = json.loads((args.research/'dump-manifest.json').read_text())
        uids = ['0DF58A36','9D1A8636']
        for uid in uids:
            row = next(r for r in dumps if r['uid']==uid)
            raw = (args.research/'dumps'/row['path']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==row['sha256']
            (root/'home/lava/bambu-dumps'/(uid+'.bin')).write_bytes(raw)
        def request(url, body=None, headers=None):
            with urlopen(Request(url, data=None if body is None else json.dumps(body).encode(),
                    headers=headers or {'Content-Type':'application/json'}), timeout=15) as r:
                return json.load(r)
        def api(path, body=None):
            return request(f'http://127.0.0.1:{descriptor["port"]}/api/'+path, body,
                {'Content-Type':'application/json','X-Tracker-Token':descriptor['token']})
        def state(): return api('state')
        def publish():
            status = rpc(root,'objects/query',objects={'tracker_uid':None})['status']['tracker_uid']
            pending = wire.with_suffix('.pending'); pending.write_text(json.dumps(status)); pending.replace(wire)
            return status
        def launch():
            nonlocal app, descriptor
            old = descriptor.get('token')
            app = subprocess.Popen([str(args.exe)],env=dict(os.environ,TRACKER20_DATA_DIR=str(profile)),stdout=log,stderr=log)
            def ready():
                nonlocal descriptor
                if app.poll() is not None: raise RuntimeError('Packaged app exited')
                descriptor = json.loads((profile/'instance.json').read_text())
                return descriptor['token']!=old and state()
            wait(ready)
        def stop():
            api('connections_stop',dict(confirmed=True))
            app.terminate(); assert app.wait(30)==0
            assert not (profile/'instance.json').exists()
        try:
            with spoolman(args,base/'spoolman') as url, klippy(root,False) as info:
                assert info['state']=='ready'; fleet = Fleet(root); publish()
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
                printer = 'http://127.0.0.1:'+str(port)
                sim = subprocess.Popen([sys.executable,str(ROOT/'dev/labs/uid_candidate_bench/simulator.py'),
                    str(port),'--reader-status-file',str(wire)],stdout=log,stderr=log)
                wait(lambda:request(printer+'/ready')); launch()
                api('settings',dict(values=dict(language='ru',printers=[dict(id='a',name='Archive bench',url=printer)],
                    selected_printer='a',spoolman_url=url,spoolman_mode='send'),expected_revision=state()['settings']['revision']))
                api('connections_start',dict(confirmed=True))
                def select(uid):
                    remove(root,fleet); publish()
                    wait(lambda:not any(r.get('uid') for r in state()['occupied']))
                    decoded = scan(root,fleet,uid); publish()
                    wait(lambda:any(r.get('uid')==uid for r in state()['occupied']))
                    return decoded
                first_tag = select(uids[0])
                assert first_tag['material']=='PLA' and first_tag['color']=='C12E1F'
                assert not state()['spools']
                review = api('rfid_preview',dict(printer_id='a',channel='0',uid=uids[0]))
                first = api('rfid_confirm',dict(review_id=review['review_id'],action='new',confirmed=True,
                    values=dict(remaining_g=840.123,density=1.24,diameter=1.75,nominal=1000)))
                sid = first['spool_id']
                remote,_ = Client(url).request('GET','/spool'); assert len(remote)==1
                assert round(remote[0]['remaining_weight'],3)==840.123
                checks.append('Delivered rc2 binary decodes real module status; PLA/C12E1F; new spool confirmation creates 840.123 g')
                # Explicitly simulate consumption at the authoritative server.
                # Real accounting/debit is covered separately by roll_identity_run.
                Client(url).request('PUT','/spool/'+str(remote[0]['id'])+'/use',dict(use_weight=20))
                second_tag = select(uids[1])
                wait(lambda:any((r.get('spool') or {}).get('spool_id')==sid for r in state()['occupied']))
                wait(lambda:state()['spools'][0]['remaining_mg']==820123)
                remote,_ = Client(url).request('GET','/spool'); assert len(remote)==1
                checks.append('Different Bambu UID automatically uses same spool and restores 820.123 g from official Spoolman')
                stop(); launch(); api('connections_start',dict(confirmed=True)); select(uids[0])
                wait(lambda:any((r.get('spool') or {}).get('spool_id')==sid for r in state()['occupied']))
                assert len(state()['spools'])==1 and state()['spools'][0]['remaining_mg']==820123
                stop(); checks.append('Packaged app restart and first-side return preserve identity and remaining balance')
                radio = rpc(root,'objects/query',objects={'multibrand_radio':None})['status']['multibrand_radio']
                assert radio['rf_commands']>0 and radio['write_commands']==0
            trial.rollback()
        finally:
            if app and app.poll() is None: app.terminate(); app.wait(30)
            if sim: sim.terminate(); sim.wait(15)
        report = dict(success=True,checks=checks,build=build,module_sha256=manifest['files']['tracker_uid.py'],
            archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
            executable_sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest(),radio=radio,
            real_printer_used=False,native_gui_tested=False,
            transport='real Klippy Unix socket -> unchanged status JSON -> loopback Moonraker subset -> packaged Mac rc2',
            spoolman='official 0.27.1; temporary local database; 20 g use request simulated explicitly',
            hardware='RF/SPI/GPIO/MCU simulated')
        (args.output/'results.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))


if __name__=='__main__': main()
