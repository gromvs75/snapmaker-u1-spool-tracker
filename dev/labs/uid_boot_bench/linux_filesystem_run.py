"""Disposable Linux mounts: real OverlayFS cleanup and real tmpfs ENOSPC.

Requires root inside a disposable Linux runner. Never run on a printer. Uses
synthetic driver bytes for filesystem checks; this is not driver compatibility.
'Cold boot' is an unmount/upper cleanup/remount, not a VM or hardware reboot.
"""
import argparse
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[3]

def load(path):
    spec=importlib.util.spec_from_file_location('trial_fs',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.APPROVED_DRIVER=m.digest(b'# synthetic driver for Linux filesystem only\n')
    return m

def command(*args):return subprocess.run(list(map(str,args)),check=True,capture_output=True,text=True)

def seed(m,root):
    for name in (m.MAIN,m.DRIVER):(root/name).parent.mkdir(parents=True,exist_ok=True)
    (root/m.DRIVER).write_bytes(b'# synthetic driver for Linux filesystem only\n')
    (root/m.MAIN).write_bytes(b'[printer]\nkinematics: none\n'+m.AUTOSAVE+b'\n#*# [probe]\n#*# z_offset = 1.25\n')
    (root/m.MAIN).chmod(0o640);os.chown(root/m.MAIN,1000,1000)
    module=root/'fixture-module.py';module.write_text('SUPPORTED_DRIVERS = '+repr({m.APPROVED_DRIVER:'fixture'})+'\n')
    return m.Trial(root),module

def fill(path):
    with path.open('wb',buffering=0) as f:
        for size in (65536,1):
            try:
                while True:f.write(b'x'*size)
            except OSError as exc:
                assert exc.errno==errno.ENOSPC
    assert os.statvfs(path).f_bavail==0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert sys.platform=='linux' and os.geteuid()==0
    a.output.mkdir(parents=True,exist_ok=False);results=[];mounts=[]
    with tempfile.TemporaryDirectory(prefix='tracker-linux-') as temp:
        base=Path(temp)
        try:
            for label,path in [('archive-installer-source',a.baseline),('fixed-source',ROOT/'scripts/rfid_u1_trial.py')]:
                m=load(path);root=base/label;t,module=seed(m,root);t.install(t.plan(module,['bambu']),module)
                recovery=root/m.RECOVERY;saved=base/(label+'-saved');shutil.copytree(recovery,saved)
                command('mount','-t','tmpfs','-o','size=2m','tmpfs',recovery);mounts.append(recovery)
                shutil.copytree(saved,recovery,dirs_exist_ok=True);fill(recovery/'filler')
                try:outcome=t.disable();error=None
                except OSError as exc:outcome=None;error=exc.errno
                active=(root/m.CFG).exists()
                assert active==(label=='archive-installer-source')
                if label=='fixed-source':assert outcome['state']=='disabled' and outcome['warnings']
                else:assert error==errno.ENOSPC
                results.append(dict(case='real ENOSPC in recovery',installer=label,errno=error,activation_remains=active,result=outcome))
                (recovery/'filler').unlink();t.rollback()
                command('umount',recovery);mounts.remove(recovery)
            m=load(ROOT/'scripts/rfid_u1_trial.py')
            root=base/'full-extras';t,module=seed(m,root);extras=(root/m.DRIVER).parent;raw=(root/m.DRIVER).read_bytes()
            command('mount','-t','tmpfs','-o','size=2m','tmpfs',extras);mounts.append(extras);(root/m.DRIVER).write_bytes(raw)
            fill(extras/'filler');plan=t.plan(module,['bambu'])
            try:t.install(plan,module)
            except OSError as exc:assert exc.errno==errno.ENOSPC
            else:raise AssertionError('Full extras unexpectedly accepted installation')
            assert not (root/m.CFG).exists();(extras/'filler').unlink()
            command(sys.executable,'-I',root/m.RECOVERY/'rfid_u1_trial.py','rollback','--offline-root',root)
            results.append(dict(case='real ENOSPC during module install',recovered=True,activation_remains=False))
            command('umount',extras);mounts.remove(extras)
            # Mount a persistent config tree inside the merged disposable system.
            lower=base/'lower';t,module=seed(m,lower)
            persistent=base/'persistent';shutil.copytree(lower/'home/lava/printer_data',persistent)
            os.chown(persistent/'config/printer.cfg',1000,1000)
            upper=base/'upper';work=base/'work';merged=base/'merged'
            for d in (upper,work,merged):d.mkdir()
            def boot():
                command('mount','-t','overlay','overlay','-o',f'lowerdir={lower},upperdir={upper},workdir={work}',merged);mounts.append(merged)
                dest=merged/'home/lava/printer_data';command('mount','--bind',persistent,dest);mounts.append(dest)
            def down():
                for d in (merged/'home/lava/printer_data',merged):command('umount',d);mounts.remove(d)
            boot();t=m.Trial(merged);before=(merged/m.MAIN).read_bytes();t.install(t.plan(module,['bambu']),module)
            info=(merged/m.MAIN).stat();assert (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))==(1000,1000,0o640)
            assert not (merged/'oem/.debug').exists()
            (merged/m.MAIN).write_bytes((merged/m.MAIN).read_bytes().replace(b'1.25',b'1.42'))
            down();shutil.rmtree(upper);upper.mkdir();shutil.rmtree(work);work.mkdir();boot()
            assert not (merged/m.CFG).exists() and not (merged/m.MODULE).exists()
            standalone=merged/m.RECOVERY/'rfid_u1_trial.py';assert standalone.exists()
            for action in ('disable','rollback','rollback'):
                command(sys.executable,'-I',standalone,action,'--offline-root',merged)
            assert (merged/m.MAIN).read_bytes()==before.replace(b'1.25',b'1.42')
            info=(merged/m.MAIN).stat();assert (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))==(1000,1000,0o640)
            results.append(dict(case='real OverlayFS unmount/upper cleanup/remount',standalone_recovery=True,klippy_used=False,mode='0640',uid=1000,gid=1000,calibration_preserved=True,actual_os_reboot=False))
            down()
        finally:
            for d in reversed(mounts):subprocess.run(['umount',str(d)],check=False,capture_output=True)
    report=dict(success=True,system=command('uname','-a').stdout.strip(),cases=results,real_printer_used=False,limitations=['Synthetic driver/module fixture','Host runner is not U1 firmware','Overlay cleanup/remount is not an actual OS reboot','xattrs/ACL and actual U1 symlink layout not established'])
    (a.output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
