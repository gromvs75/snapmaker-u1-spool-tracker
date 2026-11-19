"""Fail the UID extra import, then boot real Klippy without that extra."""
import argparse
from contextlib import closing
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.debug_loader import SERVICE
from dev.labs.uid_boot_bench.optional import AUTOSAVE, CFG
from dev.labs.uid_boot_bench.selective import ENABLED
from gcode import parse_u1_gcode
from tracker_uid_accounting import UidAccounting, mg
from tracker_uid_catalog import UidCatalog

FAULT = 'bench rejected tracker_uid/status'
FAULT_FIXTURE = """
import os
def load_config(config):
    hooks = config.get_printer().lookup_object('webhooks')
    register = hooks.register_endpoint
    def guarded(name, callback):
        if name == 'tracker_uid/status' and os.environ.get('BENCH_UID_FAIL') == '1':
            raise config.error('bench rejected tracker_uid/status')
        return register(name, callback)
    hooks.register_endpoint = guarded
    return hooks
"""
MESH = """[bed_mesh default]
version = 1
points =
  0.12, 0.13, 0.14
  0.15, 0.16, 0.17
  0.18, 0.19, 0.20
x_count = 3
y_count = 3
min_x = 0
max_x = 50
min_y = 0
max_y = 50
mesh_x_pps = 0
mesh_y_pps = 0
algo = lagrange
tension = 0.2"""


def rpc(root, method, **params):
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(3)
        stream.connect(str(root / 'api.sock'))
        stream.sendall(json.dumps(dict(id=1, method=method, params=params)).encode() + b'\x03')
        response = bytearray()
        while b'\x03' not in response:
            chunk = stream.recv(65536)
            if not chunk:
                raise ConnectionError('Klippy closed its socket')
            response.extend(chunk)
    return json.loads(response.split(b'\x03', 1)[0])['result']


@contextmanager
def klippy(root, fail):
    command = [sys.executable, str(root / 'klipper/klippy/klippy.py'), str(root / tool.MAIN),
               '-a', str(root / 'api.sock'), '-I', str(root / 'pty'), '-d', str(root / 'mcu.dict'),
               '-o', str(root / 'mcu.output')]
    marker = root / '.klipper-running'
    with (root / 'process.log').open('wb') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log, cwd=root,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                                         BENCH_UID_FAIL=str(int(fail))))
        try:
            marker.touch()
            for _ in range(150):
                if proc.poll() is not None:
                    raise RuntimeError((root / 'process.log').read_text()[-3500:])
                try:
                    info = rpc(root, 'info')
                    if info['state'] != 'startup':
                        break
                except OSError:
                    pass
                time.sleep(.1)
            else:
                raise TimeoutError((root / 'process.log').read_text()[-3500:])
            print('Klippy', proc.pid, info['state'], info['state_message'].splitlines()[0], flush=True)
            yield info
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            marker.unlink(missing_ok=True)


def manual_print(root, jobs):
    job = 'no-tag.gcode'
    (jobs / job).write_text('G90\nM400\n; filament used [g] = 1.25,0,0,0\n')
    def snapshot():
        objects = rpc(root, 'objects/list')['objects']
        assert 'tracker_uid' not in objects
        status = rpc(root, 'objects/query', objects={'webhooks': ['state'], 'print_stats': None})['status']
        channels = {str(i): {'state': 'unknown', 'uid': None} for i in range(4)}
        return {'bench': dict(printer_id='bench', state='module_missing', channels=channels,
                              printer_connected=status['webhooks']['state'] == 'ready',
                              print_state=status['print_stats']['state'])}

    with closing(UidCatalog(root / 'manual.sqlite')) as catalog:
        ledger = UidAccounting(catalog)
        spool = catalog.register_manual('Bench PLA', 500000, spool_id='manual-t0')
        assert spool['uid'] is None
        ledger.assign_manual('bench', '0', spool['spool_id'], snapshot(), confirmed=True)
        key = ledger.begin('bench', job, str(time.time()), ['0'], 'virtual-sd', snapshot())
        rpc(root, 'gcode/script', script='SDCARD_PRINT_FILE FILENAME=' + job)
        for _ in range(80):
            stats = rpc(root, 'objects/query', objects={'print_stats': None})['status']['print_stats']
            if stats['state'] == 'complete' and stats['filename'] == job:
                break
            time.sleep(.1)
        else:
            raise AssertionError(stats)
        ledger.observe(snapshot())
        usage = {'0': mg(parse_u1_gcode(jobs / stats['filename'])[0])}
        for expected in ('applied', 'duplicate'):
            assert ledger.apply(key, 1, usage, state='completed', source='virtual-sd',
                                basis='completed_gcode') == expected
        row = catalog.db.execute('SELECT uid, remaining_mg FROM uid_spools WHERE spool_id=?',
                                 (spool['spool_id'],)).fetchone()
        assert tuple(row) == (None, 498750)
        assert catalog.db.execute('SELECT count(*) FROM uid_debits').fetchone()[0] == 1
        print('PASS virtual SD complete, manual T0 without UID, 500.000 -> 498.750 g, one debit')


def exercise(root, source, kit, dictionary):
    shutil.copytree(source, root / 'klipper', ignore=shutil.ignore_patterns('.git', '__pycache__'))
    shutil.copyfile(dictionary, root / 'mcu.dict')
    extras = root / 'klipper/klippy/extras'
    (extras / 'bench_load_fault.py').write_text(FAULT_FIXTURE)
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    main = root / tool.MAIN
    main.parent.mkdir(parents=True)
    jobs = root / 'jobs'
    jobs.mkdir()
    main.write_text(f'[mcu]\nserial: /no-hardware\n[printer]\nkinematics: none\n'
                    f'max_velocity: 100\nmax_accel: 1000\n[virtual_sdcard]\npath: {jobs}\n'
                    '[bench_radio]\n[bench_load_fault]\n[bed_mesh]\nmesh_min: 0,0\nmesh_max: 50,50\n'
                    + AUTOSAVE.decode() + ''.join('#*# ' + row + '\n' for row in MESH.splitlines()))
    service = root / SERVICE
    service.parent.mkdir(parents=True)
    tool.atomic(service, b'#!/bin/sh\necho STOCK\n', 0o755)
    model = BootModel.prepare(root)
    def cli(*args):
        return json.loads(subprocess.check_output([sys.executable, '-I', str(kit / 'launch.py'),
                          *args, '--simulator-root', str(root)], text=True))
    rev = cli('plan')['revision']
    cli('install', '--reviewed-revision', rev, '--accept-whole-overlay')
    calibrated = main.read_bytes()

    def dispatch():
        model.cold_boot()
        lines = subprocess.check_output([str(service), 'start'], text=True).splitlines()
        assert lines[-1] == 'STOCK'
        assert main.read_bytes() == calibrated
        return json.loads(lines[0])

    def mesh():
        return rpc(root, 'objects/query', objects={'bed_mesh': ['profiles']})['status']['bed_mesh']['profiles']['default']['points']

    assert dispatch()['state'] == 'active'
    with klippy(root, False) as info:
        assert info['state'] == 'ready', info
        assert rpc(root, 'tracker_uid/status')['state'] == 'ready'
        points = mesh()
        assert points == [[.12,.13,.14],[.15,.16,.17],[.18,.19,.20]]
    assert dispatch()['state'] == 'active'
    with klippy(root, True) as info:
        assert info['state'] == 'ready', info
        status = rpc(root, 'objects/query', objects={'tracker_uid': None})['status']['tracker_uid']
        assert status['state'] == 'unavailable' and FAULT in status['reason'], status
    # API registration errors now fail closed inside the optional observer.
    # A broken Python file still exercises Klippy's real module-load failure.
    (root / tool.TARGETS[0]).write_bytes(b'def load_config(:\n')
    with klippy(root, True) as info:
        assert info['state'] == 'error', info

    # Disable through the installed guard's existing opt-in. Keep the fault
    # injected on every subsequent launch, so repairing the fixture cannot mask it.
    (root / ENABLED).unlink()
    for attempt in range(2):
        result = dispatch()
        assert result['state'] == 'disabled' and result['reason'] == 'not-enabled', result
        assert not (root / CFG).exists() and model.debug.exists()
        with klippy(root, True) as info:
            assert info['state'] == 'ready', info
            objects = rpc(root, 'objects/list')['objects']
            assert 'tracker_uid' not in objects and 'bench_radio' in objects
            assert 'tracker_uid/status' not in rpc(root, 'list_endpoints')['endpoints']
            rpc(root, 'bench_radio/clear', channel=0)
            for _ in range(50):
                radio = rpc(root, 'objects/query', objects={'bench_radio': ['stock_callbacks']})
                if radio['status']['bench_radio']['stock_callbacks']:
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Stock reader did not acknowledge clear')
            assert mesh() == points
            if attempt == 0:
                manual_print(root, jobs)
    print('PASS both disabled starts; unchanged printer.cfg SHA-256', tool.sha(main.read_bytes()))
    print('PASS parsed nine-point calibration', points)


if __name__ == '__main__':
    args = argparse.ArgumentParser(description=__doc__)
    for name in ('klipper', 'dictionary', 'archive'):
        args.add_argument(name, type=Path)
    paths = args.parse_args()
    with tempfile.TemporaryDirectory(prefix='uid-fault-', dir='/private/tmp') as tmp:
        root = Path(tmp)
        with ZipFile(paths.archive) as bundle:
            bundle.extractall(root / 'kit')
        exercise(root / 'sim', paths.klipper, root / 'kit', paths.dictionary)
