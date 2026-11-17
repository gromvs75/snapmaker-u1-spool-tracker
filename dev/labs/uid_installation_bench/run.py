"""Exercise the EXPORTED kit against two real no-hardware Klipper/Moonraker pairs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'dev/labs/uid_multi_bench'),str(ROOT/'src')]
import run as multi
from tracker_uid_client import UidClient,PrinterEndpoint
from tracker_printer_capabilities import manual_edit_available


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='rfid-installation-',dir='/private/tmp'));multi.ROOT=root/'printers'
    kit=root/'kit'
    # We own the produced archive; still reject paths rather than extract arbitrary names.
    with zipfile.ZipFile(args.kit) as z:
        assert set(z.namelist())=={'rfid_module_tool.py','tracker_uid.py','README-RU.md','README-EN.md','manifest.json'}
        z.extractall(kit)
    checks=[];printers=[];clients=[];result={'success':False,'root':str(root),'checks':checks,'kit_sha256':hashlib.sha256(args.kit.read_bytes()).hexdigest()}
    def check(label,truth=True):assert truth,label;checks.append(label);print('PASS '+label,flush=True)
    def cli(p,action,plan=None,ok=True):
        cmd=[sys.executable,str(kit/'rfid_module_tool.py'),action,'--simulator-root',str(p.root)]
        if plan:cmd+=['--plan',str(plan)]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        with (out/'installer.log').open('a') as f:f.write(json.dumps(dict(printer=p.pid,action=action,code=r.returncode,stdout=r.stdout,stderr=r.stderr))+'\n')
        assert (r.returncode==0)==ok,(cmd,r.stdout,r.stderr)
        return json.loads(r.stdout)
    try:
        for pid,port in [('a',18801),('b',18802)]:
            p=multi.Printer(pid,port);printers.append(p);p.installer.rollback()
            driver=p.root/'klipper/klippy/extras/fm175xx_reader.py';original=driver.read_bytes()
            p.start();multi.wait(lambda:p.http('/printer/info')['result']['state']=='ready')
            client=UidClient(PrinterEndpoint(pid,pid,p.url),poll_interval=.2,response_timeout=2);clients.append(client);client.start()
            multi.wait(lambda:client.snapshot()['state']=='module_missing')
            check(pid+': stock Klipper ready without UID; manual capability available',manual_edit_available(client.snapshot()))
            plan=root/(pid+'-plan.json');plan.write_text(json.dumps(cli(p,'plan')))
            cli(p,'install',plan,ok=False)
            check(pid+': exported kit refuses installation while process runs',not (p.root/'klipper/klippy/extras/tracker_uid.py').exists())
            p.stop_k()
            cli(p,'install',plan);cli(p,'install',plan)
            check(pid+': kit installed idempotently; original driver unchanged',driver.read_bytes()==original and cli(p,'inspect')['files_match'])
            p.start_k();multi.wait(lambda:client.snapshot()['state']=='ready')
            epoch=client.snapshot()['epoch'];p.scan(2,'04AABBCC');multi.wait(lambda:client.snapshot()['channels']['2'].get('uid')=='04AABBCC')
            check(pid+': installed extra loads and delivers observed UID via Moonraker')
            cli(p,'rollback',ok=False);check(pid+': rollback refused while process runs')
            p.stop_k();cli(p,'rollback');cli(p,'rollback');p.start_k()
            multi.wait(lambda:client.snapshot()['state']=='module_missing')
            check(pid+': rollback restores stock ready printer with no stale UID',all(c['uid'] is None for c in client.snapshot()['channels'].values()) and driver.read_bytes()==original and (p.data/'config/printer.cfg').read_bytes()==p.before)
            p.stop_k();plan.write_text(json.dumps(cli(p,'plan')));cli(p,'install',plan);p.start_k()
            multi.wait(lambda:client.snapshot()['state']=='ready' and client.snapshot()['epoch']!=epoch)
            check(pid+': reinstall creates fresh epoch with initially unknown channels',all(c['uid'] is None for c in client.snapshot()['channels'].values()))
            p.scan(1,'04112233445566');multi.wait(lambda:client.snapshot()['channels']['1'].get('uid')=='04112233445566')
            check(pid+': seven-byte UID works after reinstall')
        check('both printers remain independent and ready',all(c.snapshot()['state']=='ready' for c in clients))
        result['success']=True
    finally:
        for c in clients:c.stop()
        for p in printers:
            p.close()
            for name in ('klippy','moonraker'):shutil.copy2(p.data/f'logs/{name}.log',out/f'{p.pid}-{name}.log')
        result['processes_stopped']=all(p.k is None and p.m is None for p in printers)
        (out/'results.json').write_text(json.dumps(result,indent=2))
    print(f'{len(checks)} checks passed; both modules rolled back; processes stopped')


if __name__=='__main__':main()
