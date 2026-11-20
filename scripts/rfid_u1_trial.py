"""Reversible one-boot trial on an OFFLINE U1 filesystem copy, never a live root.

No network, process/service control, .debug, init changes or firmware flashing.
Relative optional include survives stock overlay cleanup without a missing extra.
The installed copy provides stdlib-only disable/rollback even with broken Klippy.
"""
import argparse
import ast
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

VERSION = '0.7.0-trial'
APPROVED_DRIVER = 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
EXTRAS = 'home/lava/klipper/klippy/extras/'
DRIVER = EXTRAS + 'fm175xx_reader.py'
MODULE = EXTRAS + 'tracker_uid.py'
CFG = EXTRAS + 'tracker_uid_boot.cfg'
MAIN = 'home/lava/printer_data/config/printer.cfg'
RECOVERY = 'home/lava/printer_data/tracker-rfid-recovery'
RECORD = RECOVERY + '/installation.json'
BLOCK = b'\n# BEGIN TRACKER RFID TRIAL\n[include ../../klipper/klippy/extras/[t]racker_uid_boot.cfg]\n# END TRACKER RFID TRIAL\n'
AUTOSAVE = b'#*# <---------------------- SAVE_CONFIG ---------------------->'
FORMATS = ('bambu','qidi','anycubic','creality','elegoo','tigertag','generic_ndef','opentag','openprinttag')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def atomic(path, raw, mode=0o600):
    previous=path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix='.rfid-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            if previous:
                current=os.fstat(stream.fileno())
                if (current.st_uid,current.st_gid)!=(previous.st_uid,previous.st_gid):
                    os.fchown(stream.fileno(),previous.st_uid,previous.st_gid)
            os.fchmod(stream.fileno(), mode)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync(path.parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def sync(directory):
    fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


class Trial:
    def __init__(self, root):
        root=Path(root).absolute()
        if any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('Use a canonical offline filesystem path')
        self.root=root.resolve(strict=True)
        if self.root==Path('/'):
            raise ValueError('Live root is not supported; offline rehearsal only')
        # Explicit offline images/fixtures only; never infer that services stopped
        # from a missing pidfile or attempt to stop the host/printer.
        if (self.root/'proc').exists():
            raise ValueError('Offline copy must not contain a proc mount/directory')

    def path(self,name):
        parts=Path(name).parts
        if Path(name).is_absolute() or '..' in parts:raise ValueError('Unsafe trial path')
        current=self.root
        for part in parts:
            current=current/part
            if current.is_symlink():raise ValueError('Symlink trial path')
            if current.exists() and not (current.is_file() or current.is_dir()):raise ValueError('Special trial path')
            if current.is_file() and current.stat().st_nlink!=1:raise ValueError('Hardlinked trial file')
        return current

    @contextlib.contextmanager
    def locked(self):
        import fcntl
        path=self.path('home/lava/printer_data/.tracker-rfid-trial.lock')
        with path.open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield

    def graph(self):
        result={}
        def visit(path,active):
            relative=str(path.relative_to(self.root))
            path=self.path(relative)
            if relative in active:raise ValueError('Configuration include cycle')
            if relative in result:return
            if len(result)>=200:raise ValueError('Configuration include limit')
            raw=path.read_bytes();result[relative]=digest(raw)
            for line in raw.decode().splitlines():
                if re.match(r'\s*\[tracker_uid\]',line):raise ValueError('Existing RFID configuration')
                match=re.match(r'\s*\[include\s+(.+)\]\s*(?:#.*)?$',line)
                if not match:continue
                pattern=match[1].strip()
                if pattern.startswith('/'):
                    parent=self.root;pattern=pattern.lstrip('/')
                else:parent=path.parent
                import fnmatch
                if fnmatch.fnmatchcase(str(self.path(CFG)),os.path.abspath(parent/pattern)):
                    raise ValueError('Existing include would load the trial config twice')
                import glob
                targets=glob.glob(str(parent/pattern))
                if not targets and not glob.has_magic(pattern):raise ValueError('Missing configuration include')
                for target in targets:
                    # resolve .. without following unverified symlinks.
                    target=Path(os.path.abspath(target))
                    visit(target,active|{relative})
        visit(self.path(MAIN),set())
        return result

    def plan(self,module,formats):
        if self.path('oem/.debug').exists():
            raise ValueError('Existing .debug: one-boot cleanup is not assured')
        if any(self.path(p).exists() for p in (RECORD,MODULE,CFG)):
            raise ValueError('Existing trial or RFID files; recover/review first')
        if set(formats)-set(FORMATS) or len(formats)!=len(set(formats)):
            raise ValueError('Unsupported/duplicate RFID format')
        source=Path(module).read_bytes()
        tree=ast.parse(source)
        supported=None
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SUPPORTED_DRIVERS' for t in node.targets):
                supported=ast.literal_eval(node.value)
        driver=digest(self.path(DRIVER).read_bytes())
        if not isinstance(supported,dict) or driver not in supported or driver!=APPROVED_DRIVER:raise ValueError('Unsupported stock driver for this deployment trial')
        graph=self.graph()
        main=self.path(MAIN).read_bytes()
        if b'TRACKER RFID TRIAL' in main:raise ValueError('Unowned trial include')
        config=('[tracker_uid]\nenabled: True\n'+''.join(n+'_read_enabled: True\n' for n in formats)).encode()
        data=dict(schema=1,version=VERSION,root=str(self.root),driver_sha256=driver,
                  firmware=supported[driver],configuration=graph,formats=list(formats),
                  module_sha256=digest(source),config=base64.b64encode(config).decode(),
                  main_mode=stat.S_IMODE(self.path(MAIN).stat().st_mode),
                  persistence='one-boot; no .debug',physical_installation=False)
        return dict(data,revision=digest(canonical(data)))

    def read(self):
        value=json.loads(self.path(RECORD).read_text())
        revision=value.pop('revision')
        if value.get('schema')!=1 or value.get('root')!=str(self.root) or digest(canonical(value))!=revision:
            raise ValueError('Invalid installation record')
        return value

    def install(self,plan,module,fail_after=None):
        with self.locked():
            if plan!=self.plan(module,plan['formats']):raise ValueError('Stale installation plan')
            recovery=self.path(RECOVERY)
            if recovery.exists():raise ValueError('Recovery directory already exists')
            recovery.mkdir(mode=0o700)
            sync(recovery.parent)
            main=self.path(MAIN).read_bytes()
            record=dict(schema=1,root=str(self.root),plan=plan,
                        main_before=base64.b64encode(main).decode(),block=base64.b64encode(BLOCK).decode())
            atomic(self.path(RECORD),canonical(dict(record,revision=digest(canonical(record)))))
            atomic(recovery/'rfid_u1_trial.py',Path(__file__).read_bytes())
            if fail_after==0:raise RuntimeError('Interrupted after recovery record')
            atomic(self.path(MODULE),Path(module).read_bytes(),0o644)
            if fail_after==1:raise RuntimeError('Interrupted after module')
            position=main.find(AUTOSAVE)
            configured=main+BLOCK if position<0 else main[:position]+BLOCK+main[position:]
            atomic(self.path(MAIN),configured,plan['main_mode'])
            if fail_after==2:raise RuntimeError('Interrupted before activation')
            atomic(self.path(CFG),base64.b64decode(plan['config'],validate=True),0o644)
            return dict(state='installed',persistence=plan['persistence'],physical_installation=False)

    def _disable(self,record):
        # No module import, driver/config parsing, network or Klipper API.
        cfg=self.path(CFG)
        warnings=[]
        raw=None
        if cfg.exists():
            try:raw=cfg.read_bytes()
            except OSError as exc:warnings.append('Activation backup unavailable: '+str(exc))
            # Removing the optional include target is the safety-critical operation.
            # Diagnostic writes must never prevent OFF on a full/read-only recovery volume.
            cfg.unlink();sync(cfg.parent)
        if raw is not None:
            try:
                archive=self.path(RECOVERY+'/disabled')
                archive.mkdir(mode=0o700,exist_ok=True)
                atomic(archive/(digest(raw)+'.cfg'),raw)
            except OSError as exc:warnings.append('Activation backup not saved: '+str(exc))
        try:
            atomic(self.path(RECOVERY+'/disabled.json'),canonical(dict(effective='next-klipper-start')))
        except OSError as exc:warnings.append('OFF receipt not saved: '+str(exc))
        result=dict(state='disabled',effective='next-klipper-start',physical_installation=False)
        if warnings:result['warnings']=warnings
        return result

    def disable(self):
        with self.locked():return self._disable(self.read())

    def rollback(self,fail_after=None):
        with self.locked():
            record=self.read();self._disable(record)
            if fail_after==0:raise RuntimeError('Interrupted after disable')
            main=self.path(MAIN);raw=main.read_bytes()
            block=base64.b64decode(record['block'],validate=True)
            if block!=BLOCK:raise ValueError('Invalid owned include')
            if raw.count(block)>1:raise ValueError('Duplicate owned include; activation disabled')
            if b'TRACKER RFID TRIAL' in raw and block not in raw:raise ValueError('Edited owned include; activation disabled')
            if block in raw:atomic(main,raw.replace(block,b'',1),stat.S_IMODE(main.stat().st_mode))
            if fail_after==1:raise RuntimeError('Interrupted after include removal')
            module=self.path(MODULE)
            if module.exists():
                raw=module.read_bytes()
                if digest(raw)!=record['plan']['module_sha256']:
                    # Keep a corrupted/edited module for diagnosis before removal.
                    atomic(self.path(RECOVERY+'/retained-module.py'),raw)
                module.unlink();sync(module.parent)
            result=dict(state='rolled-back',recovery_retained=True,physical_installation=False)
            atomic(self.path(RECOVERY+'/rollback.json'),canonical(result))
            return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','install','disable','rollback'))
    parser.add_argument('--offline-root',type=Path,required=True)
    parser.add_argument('--module',type=Path)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--formats',default='bambu')
    args=parser.parse_args()
    try:
        trial=Trial(args.offline_root)
        if args.action=='plan':result=trial.plan(args.module,args.formats.split(',') if args.formats else [])
        elif args.action=='install':result=trial.install(json.loads(args.plan.read_text()),args.module)
        else:result=getattr(trial,args.action)()
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps(dict(state='review-required',error=str(exc))));return 1


if __name__=='__main__':raise SystemExit(main())
