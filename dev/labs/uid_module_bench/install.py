"""Filesystem installation/rollback rehearsal. Explicitly rejects non-simulator roots.

No SSH, subprocess, service control or printer connections. Stop simulated Klipper
before using this tool; a future real deployment tool needs separate authorization.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

MARKER = {'kind':'tracker-uid-filesystem-simulator','version':1}
BLOCK = b'\n# BEGIN TRACKER UID\n[include tracker_uid.cfg]\n# END TRACKER UID\n'
CONFIG = b'[tracker_uid]\nenabled: True\nstale_after: 300\n'
MODULE = Path(__file__).resolve().parents[2]/'klipper/tracker_uid.py'


def atomic(path, content, mode=0o644):
    fd, temporary=tempfile.mkstemp(prefix='.tracker-stage-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(temporary,mode)
        os.replace(temporary,path)
        parent=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def encode(b):return base64.b64encode(b).decode()
def decode(s):return base64.b64decode(s)
def sha(b):return hashlib.sha256(b).hexdigest()


class Installer:
    def __init__(self,root):
        root=Path(root)
        if root.is_symlink():raise ValueError('Symlink root forbidden')
        self.root=root.resolve(strict=True)
        marker=self.root/'.tracker-uid-simulator.json'
        if marker.is_symlink() or json.loads(marker.read_text())!=MARKER:
            raise ValueError('Only a marked simulator root is allowed')
        self.journal=self.path('.tracker-uid-journal.json')
        self.lock_path=self.path('.tracker-uid-install.lock')

    def path(self,name):
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe path')
        p=self.root
        for part in rel.parts:
            p=p/part
            if p.is_symlink():raise ValueError('Symlink destination forbidden')
        return p

    @contextlib.contextmanager
    def locked(self):
        with self.lock_path.open('a+b') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.path('.klipper-running').exists():raise ValueError('Stop simulated Klipper first')
            yield

    def install(self, fail_after=None):
        with self.locked():
            if self.journal.exists():
                old=json.loads(self.journal.read_text())
                if old['state']=='installed':
                    for item in old['files']:
                        if self.path(item['path']).read_bytes()!=decode(item['new']):
                            raise ValueError('Installed files changed; inspect before updating')
                    if sha(MODULE.read_bytes())!=old['module_sha256']:raise ValueError('Different module build')
                    return 'already-installed'
                raise ValueError('Pending transaction: rollback first')
            driver=self.path('klipper/klippy/extras/fm175xx_reader.py')
            # Import only our hardware-free module; never import the printer driver here.
            import importlib.util
            spec=importlib.util.spec_from_file_location('tracker_uid_installer_check',MODULE)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            digest=sha(driver.read_bytes())
            if digest not in module.SUPPORTED_DRIVERS:raise ValueError('Unsupported driver hash')
            config=self.path('printer_data/config/printer.cfg')
            before=config.read_bytes()
            if b'tracker_uid' in before:raise ValueError('Existing tracker_uid configuration')
            changes=[('klipper/klippy/extras/tracker_uid.py',MODULE.read_bytes()),
                     ('printer_data/config/tracker_uid.cfg',CONFIG),
                     ('printer_data/config/printer.cfg',before+BLOCK)]
            files=[]
            for name,new in changes:
                dest=self.path(name)
                if name.endswith('/tracker_uid.py') or name.endswith('/tracker_uid.cfg'):
                    if dest.exists():raise ValueError('Destination already exists')
                original=dest.read_bytes() if dest.exists() else None
                files.append(dict(path=name,old=encode(original) if original is not None else None,
                                  new=encode(new),mode=stat.S_IMODE(dest.stat().st_mode) if dest.exists() else 0o644))
            journal=dict(state='pending',driver_sha256=digest,module_sha256=sha(MODULE.read_bytes()),files=files)
            atomic(self.journal,json.dumps(journal,indent=2).encode(),0o600)
            for n,item in enumerate(files,1):
                dest=self.path(item['path'])
                expected=decode(item['old']) if item['old'] is not None else None
                if (dest.read_bytes() if dest.exists() else None)!=expected:
                    raise ValueError('Concurrent change; rollback pending transaction')
                atomic(dest,decode(item['new']),item['mode'])
                if fail_after==n:raise RuntimeError('Simulated installation interruption')
            journal['state']='installed'
            atomic(self.journal,json.dumps(journal,indent=2).encode(),0o600)
            return 'installed'

    def rollback(self):
        with self.locked():
            if not self.journal.exists():return 'not-installed'
            journal=json.loads(self.journal.read_text())
            actions=[]
            for item in journal['files']:
                dest=self.path(item['path'])
                current=dest.read_bytes() if dest.exists() else None
                old=decode(item['old']) if item['old'] is not None else None
                new=decode(item['new'])
                if current==old:continue  # Already restored, or install stopped before this file.
                if current==new:restored=old
                elif item['path']=='printer_data/config/printer.cfg' and current is not None and current.count(BLOCK)==1:
                    restored=current.replace(BLOCK,b'',1)  # Preserve unrelated later config edits.
                else:raise ValueError('Owned file changed; refusing destructive rollback')
                actions.append((dest,restored,item['mode']))
            for dest,restored,mode in reversed(actions):
                if restored is None:dest.unlink()
                else:atomic(dest,restored,mode)
            # Journal contains the backup; retain it for diagnosis after uninstall.
            history=self.path('.tracker-uid-last-rollback.json')
            atomic(history,json.dumps(journal,indent=2).encode(),0o600)
            self.journal.unlink()
            return 'rolled-back'


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','rollback'])
    parser.add_argument('--simulator-root',type=Path,required=True)
    args=parser.parse_args()
    print(getattr(Installer(args.simulator_root),args.action)())
