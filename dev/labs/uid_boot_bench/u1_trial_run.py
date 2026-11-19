"""Actual Klippy loading/error/OFF/rollback with U1 paths in disposable roots."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.rfid_u1_trial import Trial, MAIN, MODULE, CFG, DRIVER, RECOVERY, AUTOSAVE, BLOCK
from dev.labs.uid_boot_bench.load_fault_run import klippy,rpc,FAULT_FIXTURE,MESH,manual_print


def prepare(args,root,formats=('bambu',),multibrand=False):
    klipper=root/'home/lava/klipper'
    shutil.copytree(args.klipper,klipper,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','tracker_uid.py','tracker_uid_boot.cfg'))
    (root/'klipper').symlink_to(klipper,target_is_directory=True)  # old runner's path only
    extras=klipper/'klippy/extras'
    shutil.copyfile(args.driver,root/DRIVER)
    shutil.copyfile(ROOT/'dev/labs/uid_live_bench/bench_radio.py',extras/'bench_radio.py')
    if multibrand:
        for name in ('bambu_radio.py','multibrand_radio.py'):
            shutil.copyfile(ROOT/'dev/labs/uid_live_bench'/name,extras/name)
        for name in ('bambu-dumps','other-dumps'):(root/'home/lava'/name).mkdir()
        # Constructor seed only. Generic-NDEF scenarios explicitly select their
        # Type 2 cards before reading; this is not a Bambu decoding fixture.
        (root/'home/lava/bambu-dumps/04112233.bin').write_bytes(bytes(1024))
    (extras/'bench_load_fault.py').write_text(FAULT_FIXTURE)
    shutil.copyfile(args.dictionary,root/'mcu.dict')
    config=root/MAIN;config.parent.mkdir(parents=True)
    (root/'home/lava/.tracker-uid-simulator.json').write_text('{"kind":"tracker-uid-filesystem-simulator","version":1}')
    (root/'printer_data').symlink_to(root/'home/lava/printer_data',target_is_directory=True)
    jobs=root/'jobs';jobs.mkdir()
    config.write_text('[mcu]\nserial: /no-hardware\n[printer]\nkinematics: none\nmax_velocity: 100\nmax_accel: 1000\n'
                      '[virtual_sdcard]\npath: '+str(jobs)+'\n[bench_radio]\n[bench_load_fault]\n'
                      '[bed_mesh]\nmesh_min: 0,0\nmesh_max: 50,50\n'+AUTOSAVE.decode()+'\n'
                      '#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n'
                      +''.join('#*# '+line+'\n' for line in MESH.splitlines()))
    if multibrand:config.write_text(config.read_text().replace('[bench_radio]','[multibrand_radio]'))
    return Trial(root)


def exercise(args,root,case):
    trial=prepare(args,root)
    config=root/MAIN;jobs=root/'jobs'
    original=config.read_bytes();driver=(root/DRIVER).read_bytes()
    trial=Trial(root);module=ROOT/'dev/klipper/tracker_uid.py'
    if args.archive:
        from zipfile import ZipFile
        import hashlib
        unpacked=root/'distribution';unpacked.mkdir()
        with ZipFile(args.archive) as bundle:
            manifest=json.loads(bundle.read('manifest.json'))
            for name,digest in manifest['files'].items():
                assert Path(name).name==name
                raw=bundle.read(name);assert hashlib.sha256(raw).hexdigest()==digest
                (unpacked/name).write_bytes(raw)
        command=[sys.executable,'-I',str(unpacked/'rfid_u1_trial.py')]
        tail=['--offline-root',str(root),'--module',str(unpacked/'tracker_uid.py')]
        planned=subprocess.run(command+['plan']+tail,capture_output=True,text=True,check=True)
        (root/'reviewed-plan.json').write_text(planned.stdout)
        subprocess.run(command+['install']+tail+['--plan',str(root/'reviewed-plan.json')],capture_output=True,text=True,check=True)
        shutil.rmtree(unpacked)
    else:trial.install(trial.plan(module,['bambu']),module)
    installed=config.read_bytes()
    if case=='syntax':(root/MODULE).write_bytes(b'def load_config(:\n')
    elif case=='missing':(root/MODULE).unlink()
    elif case=='bad-config':(root/CFG).write_bytes(b'[tracker_uid]\nstale_after: bad\n')
    elif case=='overlay-cleanup':
        (root/MODULE).unlink();(root/CFG).unlink()
    checks=[]
    def cli(action):
        p=subprocess.run([sys.executable,'-I',str(root/RECOVERY/'rfid_u1_trial.py'),action,
                          '--offline-root',str(root)],cwd=root,capture_output=True,text=True,timeout=10)
        assert p.returncode==0,p.stdout+p.stderr
        return json.loads(p.stdout)
    if case!='no-process':
        with klippy(root,case=='api-unavailable') as info:
            assert info['state']==('error' if case in ('syntax','missing','bad-config') else 'ready'),info
            checks.append('expected actual Klippy state: '+info['state'])
            cli('disable')
            checks.append('standalone OFF while Klippy exists')
        shutil.copyfile(root/'process.log',args.output/(case+'-before.log'))
    else:
        cli('disable');checks.append('standalone OFF without Klippy/API')
    cli('disable')
    for i in range(2):
        with klippy(root,False) as info:
            assert info['state']=='ready',info
            assert 'tracker_uid' not in rpc(root,'objects/list')['objects']
            points=rpc(root,'objects/query',objects={'bed_mesh':['profiles']})['status']['bed_mesh']['profiles']['default']['points']
            assert points==[[.12,.13,.14],[.15,.16,.17],[.18,.19,.20]]
            if case=='syntax' and i==0:manual_print(root,jobs)
        shutil.copyfile(root/'process.log',args.output/(case+'-off-'+str(i)+'.log'))
        checks.append('OFF boot ready with original mesh '+str(i+1))
    assert config.read_bytes()==installed and (root/DRIVER).read_bytes()==driver
    cli('rollback');cli('rollback')
    assert config.read_bytes()==original and not (root/MODULE).exists() and not (root/CFG).exists()
    checks.append('idempotent rollback: original config and stock driver')
    return dict(case=case,checks=checks)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('klipper','driver','dictionary','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for case in ('healthy','api-unavailable','syntax','missing','bad-config','no-process','overlay-cleanup'):
        with tempfile.TemporaryDirectory(prefix='rfid-u1-trial-',dir='/private/tmp') as tmp:
            cases.append(exercise(args,Path(tmp),case))
        print('PASS '+case,flush=True)
    (args.output/'results.json').write_text(json.dumps(dict(success=True,cases=cases,real_printer_used=False,
        hardware='simulated RF/SPI/GPIO/MCU',installation='offline U1 layout; no service control; no .debug'),indent=2))


if __name__=='__main__':main()
