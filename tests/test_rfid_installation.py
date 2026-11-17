"""Offline installation failure modes: no printer, service or application database."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX-only offline deployment tool; not Windows GUI')

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rfid_tool_test', ROOT/'scripts/rfid_module_tool.py')
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
VERSIONS = ('1.3.0.168','2.0.0.205','2.1.0.157')
# Filesystem-only fixtures. Real driver compatibility runs separately against the
# pinned source corpus in uid_module_bench + uid_bridge_bench.
DRIVERS = {v:('# synthetic driver '+v+'\n').encode() for v in VERSIONS}


@pytest.fixture
def fs(tmp_path,monkeypatch):
    root = tmp_path.resolve()/'printer'; root.mkdir()
    (root/'.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    for folder in ('klipper/klippy/extras', 'printer_data/config'):
        (root/folder).mkdir(parents=True)
    kit=tmp_path/'kit';kit.mkdir()
    (kit/'rfid_module_tool.py').write_bytes((ROOT/'scripts/rfid_module_tool.py').read_bytes())
    module=kit/'tracker_uid.py'
    module.write_text('SUPPORTED_DRIVERS = '+repr({tool.sha(b):v for v,b in DRIVERS.items()})+'\n')
    monkeypatch.setattr(tool,'MODULE',module)
    (root/tool.DRIVER).write_bytes(DRIVERS['2.0.0.205'])
    (root/tool.MAIN).write_bytes(b'# untouched\n[printer]\nkinematics: none\n')
    return root


def tree(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('version',['1.3.0.168','2.0.0.205','2.1.0.157'])
def test_known_driver_preflight_is_read_only(fs,version):
    (fs/tool.DRIVER).write_bytes(DRIVERS[version])
    original=tree(fs);i=tool.Installer(fs)
    assert i.inspect()['driver_version']==version
    assert i.inspect()['compatible']
    assert i.plan()['revision']==i.plan()['revision']
    assert tree(fs)==original


def test_unknown_or_modified_driver_cannot_install(fs):
    (fs/tool.DRIVER).write_bytes((fs/tool.DRIVER).read_bytes()+b'\n')
    i=tool.Installer(fs);assert not i.inspect()['compatible']
    with pytest.raises(ValueError,match='Unsupported'):i.install()
    assert not (fs/tool.TARGETS[0]).exists()
    assert not i.journal.exists()


@pytest.mark.parametrize('change',['main','include','driver','mode'])
def test_reviewed_plan_rejects_changed_inputs(fs,change):
    cfg=fs/'printer_data/config/extra.cfg';cfg.write_bytes(b'# extra\n')
    with (fs/tool.MAIN).open('ab') as f:f.write(b'[include extra.cfg]\n')
    i=tool.Installer(fs);plan=i.plan()
    if change=='mode':(fs/tool.MAIN).chmod(0o600)
    else:
        target={'main':fs/tool.MAIN,'include':cfg,'driver':fs/tool.DRIVER}[change]
        target.write_bytes(target.read_bytes()+b'\n')
    with pytest.raises(ValueError):i.install(expected_revision=plan['revision'])
    assert not i.journal.exists() and not (fs/tool.TARGETS[0]).exists()


@pytest.mark.parametrize('content',[
    '[tracker_uid]\n', '[include tracker_uid.cfg]\n', '[include *.cfg]\n',
    '[include ../elsewhere.cfg]\n', '[include missing.cfg]\n', '[include printer.cfg]\n',
])
def test_conflicting_or_unresolvable_includes_fail_closed(fs,content):
    extra=fs/'printer_data/config/extra.cfg';extra.write_text(content)
    with (fs/tool.MAIN).open('a') as f:f.write('[include extra.cfg]\n')
    i=tool.Installer(fs);original=(fs/tool.MAIN).read_bytes()
    assert not i.inspect()['compatible']
    with pytest.raises(ValueError):i.install()
    assert (fs/tool.MAIN).read_bytes()==original and not (fs/tool.TARGETS[0]).exists()


@pytest.mark.parametrize('step',[1,2,3])
def test_interrupted_rollback_is_resumable_with_later_config_edits(fs,step):
    i=tool.Installer(fs);original=(fs/tool.MAIN).read_bytes();i.install()
    backup=i.read_journal()['backup'];backup_bytes=(fs/backup).read_bytes()
    with (fs/tool.MAIN).open('ab') as f:f.write(b'# later edit\n')
    with pytest.raises(RuntimeError,match='rollback interruption'):i.rollback(fail_after=step)
    assert i.inspect()['state']=='rolling-back'
    assert i.rollback()=='rolled-back'
    assert (fs/tool.MAIN).read_bytes()==original+b'# later edit\n'
    assert (fs/backup).read_bytes()==backup_bytes
    assert not (fs/tool.TARGETS[0]).exists() and not (fs/tool.TARGETS[1]).exists()
    assert i.rollback()=='not-installed'


@pytest.mark.parametrize('target',['backup','journal','rollback','redirect'])
def test_corrupt_backup_or_journal_never_overwrites(fs,target):
    i=tool.Installer(fs);i.install()
    if target=='backup':
        backup=fs/i.read_journal()['backup'];backup.write_bytes(backup.read_bytes()+b' ')
    else:
        if target=='rollback':
            with pytest.raises(RuntimeError):i.rollback(fail_after=1)
        value=json.loads(i.journal.read_text())
        if target=='journal':value['files'][0]['new']='Y29ycnVwdA=='
        if target=='redirect':value['files'][0]['path']='printer_data/config/elsewhere.cfg'
        if target=='rollback':value['rollback'][0]['after']='Y29ycnVwdA=='
        i.journal.write_text(json.dumps(value))
    before=tree(fs)
    with pytest.raises(ValueError):i.rollback()
    assert tree(fs)==before


def test_repeated_install_detects_driver_upgrade_but_rollback_preserves_it(fs):
    i=tool.Installer(fs);i.install();new=b'# new driver version\n'
    (fs/tool.DRIVER).write_bytes(new)
    assert not i.inspect()['compatible']
    with pytest.raises(ValueError,match='Driver changed'):i.install()
    i.rollback();assert (fs/tool.DRIVER).read_bytes()==new


def test_reinstall_keeps_separate_immutable_backups(fs):
    i=tool.Installer(fs);i.install();one=i.read_journal()['backup'];i.rollback()
    with (fs/tool.MAIN).open('ab') as f:f.write(b'# new user configuration\n')
    i.install();two=i.read_journal()['backup'];i.rollback()
    assert one!=two and (fs/one).exists() and (fs/two).exists()


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_linked_config_rejected(fs,tmp_path,kind):
    other=tmp_path/'outside';other.write_bytes(b'keep')
    (fs/tool.MAIN).unlink()
    if kind=='symlink':(fs/tool.MAIN).symlink_to(other)
    else:__import__('os').link(other,fs/tool.MAIN)
    with pytest.raises(ValueError):tool.Installer(fs).install()
    assert other.read_bytes()==b'keep'


def test_concurrent_installer_rejected(fs):
    i=tool.Installer(fs)
    with i.locked():
        with pytest.raises(BlockingIOError):tool.Installer(fs).install()
    assert not i.journal.exists()


def test_change_between_writes_can_be_rolled_back_without_losing_edit(fs,monkeypatch):
    i=tool.Installer(fs);original=(fs/tool.MAIN).read_bytes();atomic=tool.atomic
    def interfering(path,content,mode=0o644):
        atomic(path,content,mode)
        if path==fs/tool.TARGETS[0]:
            with (fs/tool.MAIN).open('ab') as f:f.write(b'# concurrent edit\n')
    monkeypatch.setattr(tool,'atomic',interfering)
    with pytest.raises(ValueError,match='Concurrent'):i.install()
    # Config was never modified by us. Preserve the unrelated change while removing
    # the partially installed module; no replacement with an older whole config.
    with pytest.raises(ValueError,match='Owned file changed'):i.rollback()
    assert (fs/tool.MAIN).read_bytes()==original+b'# concurrent edit\n'


def test_cli_requires_exact_plan_and_rejects_unmarked_root(fs,tmp_path):
    script=tool.MODULE.with_name('rfid_module_tool.py')
    def call(action,*args,root=fs):
        return subprocess.run([sys.executable,str(script),action,'--simulator-root',str(root),*args],capture_output=True,text=True)
    assert call('install').returncode==1
    plan=tmp_path/'plan.json';plan.write_text(call('plan').stdout)
    assert call('install','--plan',str(plan)).returncode==0
    assert call('install','--plan',str(plan)).returncode==0
    assert call('rollback').returncode==0
    value=json.loads(plan.read_text());value['files'][0]['new']='bad';plan.write_text(json.dumps(value))
    assert call('install','--plan',str(plan)).returncode==1
    assert call('inspect',root=tmp_path).returncode==1


@pytest.mark.parametrize('name',['rfid_module_tool.py','tracker_uid.py','README-RU.md','README-EN.md'])
def test_exported_kit_refuses_corrupted_files_before_touching_root(fs,name):
    kit=tool.MODULE.parent
    for doc in ('README-RU.md','README-EN.md'):(kit/doc).write_text('fixture instructions')
    names=['rfid_module_tool.py','tracker_uid.py','README-RU.md','README-EN.md']
    (kit/'manifest.json').write_text(json.dumps(dict(schema=1,files={n:tool.sha((kit/n).read_bytes()) for n in names})))
    command=[sys.executable,str(kit/'rfid_module_tool.py'),'inspect','--simulator-root',str(fs)]
    assert subprocess.run(command,capture_output=True).returncode==0
    before=tree(fs)
    with (kit/name).open('ab') as f:f.write(b'\n# corrupt\n')
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==1 and 'integrity' in result.stdout
    assert tree(fs)==before
