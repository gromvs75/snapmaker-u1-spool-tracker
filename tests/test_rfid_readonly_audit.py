"""Audit untrusted/stale filesystem evidence without service or database writes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import rfid_readonly_audit as audit

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX U1 read-only diagnostics')


def test_regular_file_hash_does_not_disclose_content(tmp_path):
    (tmp_path / 'config').write_text('private setting\n')
    result = audit.inventory(tmp_path)
    assert result['complete'] == hasattr(os, 'listxattr'), result['errors']
    assert result['entries']['config']['sha256'] == audit.digest(b'private setting\n')
    assert 'private setting' not in json.dumps(result)
    assert not result['coherent_snapshot'] and not result['trusted_xattrs_complete']


def test_links_are_not_followed_and_fifos_not_opened(tmp_path):
    root = tmp_path / 'upper'
    root.mkdir()
    (tmp_path / 'private').write_text('do not read')
    (root / 'link').symlink_to(tmp_path / 'private')
    os.mkfifo(root / 'fifo')
    result = audit.inventory(root)
    assert result['entries']['link']['kind'] == 'symlink'
    assert result['entries']['fifo']['kind'] == 'fifo'
    assert 'sha256' not in result['entries']['link']
    assert 'sha256' not in result['entries']['fifo']
    assert not result['complete']  # link attributes deliberately unobserved


def test_symlink_inventory_root_refused(tmp_path):
    (tmp_path / 'link').symlink_to(tmp_path, target_is_directory=True)
    result = audit.inventory(tmp_path / 'link')
    assert not result['complete'] and not result['entries']


@pytest.mark.parametrize('limits', [{'max_entries': 1}, {'max_file_bytes': 1},
                                   {'max_total_bytes': 1}, {'max_seconds': -1}])
def test_inventory_limits_are_visible_not_false_success(tmp_path, limits):
    (tmp_path / 'large').write_bytes(b'abcd')
    result = audit.inventory(tmp_path, **limits)
    assert not result['complete'] and result['errors']


def test_hardlinked_files_require_review(tmp_path):
    (tmp_path / 'source').write_bytes(b'x')
    os.link(tmp_path / 'source', tmp_path / 'alias')
    result = audit.inventory(tmp_path)
    assert not result['complete']
    assert any('hardlink' in e for e in result['errors'])


def test_changed_file_does_not_produce_trusted_inventory(tmp_path, monkeypatch):
    p = tmp_path / 'file'
    p.write_bytes(b'original')
    original = audit.digest
    def mutate(raw):
        p.write_bytes(b'changed while reading')
        return original(raw)
    monkeypatch.setattr(audit, 'digest', mutate)
    result = audit.inventory(tmp_path)
    assert not result['complete'] and any('changed' in e for e in result['errors'])


def test_directory_replaced_by_link_during_scan_cannot_escape_root(tmp_path, monkeypatch):
    root = tmp_path / 'upper'
    root.mkdir()
    child = root / 'nested'
    child.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret').write_text('private')
    original = audit.os.open
    def replaced(name, flags, *args, **kwargs):
        if name == 'nested' and not child.is_symlink():
            child.rmdir()
            child.symlink_to(outside, target_is_directory=True)
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(audit.os, 'open', replaced)
    result = audit.inventory(root)
    assert not result['complete'] and not any('secret' in n for n in result['entries'])


def write_process(proc, pid, role='klippy.py', start=123):
    path = proc / str(pid)
    path.mkdir(parents=True)
    (path / 'cmdline').write_bytes(b'/usr/bin/python3\0/home/lava/' + role.encode() + b'\0--password=secret\0')
    # Fields 3..21, then starttime field 22. comm can contain spaces and ')'.
    fields = ['S'] + ['0'] * 18 + [str(start)]
    (path / 'stat').write_text(str(pid) + ' (python ) worker) ' + ' '.join(fields))


def test_process_identity_hides_commandline_and_environment(tmp_path):
    write_process(tmp_path, 123)
    result = audit.process_snapshot(tmp_path)
    assert result == {'processes': [{'pid': 123, 'role': 'klipper', 'state': 'S', 'start_ticks': 123}],
                      'errors': [], 'complete': True}
    assert 'secret' not in json.dumps(result)


def test_process_disappearing_is_not_claimed_as_stopped(tmp_path):
    (tmp_path / '123').mkdir()
    result = audit.process_snapshot(tmp_path)
    assert not result['complete']
    observed = audit.service_observation(result, result, '123')
    assert observed['warnings'] and not observed['stopped_proven']


@pytest.mark.parametrize('case', ['stale-pid', 'reused-pid', 'respawn', 'duplicate', 'no-process'])
def test_pidfile_and_process_races_never_authorize_writes(case):
    first = {'complete': True, 'processes': [{'pid': 10, 'start_ticks': 100, 'role': 'klipper'}]}
    second = json.loads(json.dumps(first))
    pidfile = '10'
    if case == 'stale-pid':
        pidfile = '12'
    elif case == 'reused-pid':
        second['processes'][0]['start_ticks'] = 200
    elif case == 'respawn':
        second['processes'][0]['pid'] = 11
    elif case == 'duplicate':
        second['processes'].append({'pid': 11, 'start_ticks': 200, 'role': 'klipper'})
    elif case == 'no-process':
        second['processes'] = []
    result = audit.service_observation(first, second, pidfile)
    assert result['warnings'] and not result['exclusive_control_proven']
    assert not result['stopped_proven']


def test_complete_fixture_cli_never_changes_files_or_allows_install(tmp_path):
    for name in audit.FIXED_FILES:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# synthetic source, never execute\n')
    (tmp_path / audit.UPPER).mkdir(parents=True)
    for name, text in [('proc/self/mountinfo', 'fixture mount'),
                       ('proc/sys/kernel/random/boot_id', 'fixture boot'), ('run/klipper.pid', '10')]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    write_process(tmp_path / 'proc', 10)
    def contents():
        return {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    before = contents()
    script = Path(audit.__file__)
    result = subprocess.run([sys.executable, '-B', str(script), '--fixture-root', str(tmp_path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['overlay']['complete'] == hasattr(os, 'listxattr')
    assert not data['installation_allowed']
    assert not data['service']['pinned_stop_script_matches']
    assert data['service']['observation']['warnings'] == []
    assert contents() == before


def test_missing_paths_are_reported_instead_of_green_compatibility(tmp_path):
    data = audit.collect(tmp_path)
    assert not data['installation_allowed'] and not data['overlay']['complete']
    assert all('error' in f for f in data['files'].values())


def test_unreadable_overlay_attributes_are_reported(tmp_path, monkeypatch):
    def denied(fd):
        raise PermissionError('trusted attributes unavailable')
    monkeypatch.setattr(audit.os, 'listxattr', denied, raising=False)
    data = audit.inventory(tmp_path)
    assert not data['complete'] and any('xattrs unreadable' in e for e in data['errors'])
