"""Packaged RFID OFF with real Klippy failures; only temporary synthetic roots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from dev.labs.uid_boot_bench.load_fault_run import (
    FAULT_FIXTURE, MESH, klippy, rpc, manual_print)
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.debug_loader import SERVICE, KIT
from dev.labs.uid_boot_bench.optional import AUTOSAVE, CFG
from dev.labs.uid_boot_bench.selective import ENABLED

DRIVER_HASH = 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'


def prepare(root, args):
    shutil.copytree(args.klipper, root / 'klipper',
                    ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc',
                                                 'tracker_uid.py', 'tracker_uid_boot.cfg'))
    extras = root / 'klipper/klippy/extras'
    shutil.copyfile(args.driver, extras / 'fm175xx_reader.py')
    shutil.copyfile(ROOT / 'dev/labs/uid_live_bench/bench_radio.py', extras / 'bench_radio.py')
    (extras / 'bench_load_fault.py').write_text(FAULT_FIXTURE)
    shutil.copyfile(args.dictionary, root / 'mcu.dict')
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    jobs = root / 'jobs'
    jobs.mkdir()
    main = root / tool.MAIN
    main.parent.mkdir(parents=True)
    main.write_text('[mcu]\nserial: /no-hardware\n[printer]\nkinematics: none\n'
                    'max_velocity: 100\nmax_accel: 1000\n[virtual_sdcard]\npath: '
                    + str(jobs) + '\n[bench_radio]\n[bench_load_fault]\n'
                    '[bed_mesh]\nmesh_min: 0,0\nmesh_max: 50,50\n'
                    + AUTOSAVE.decode() + ''.join('#*# ' + row + '\n' for row in MESH.splitlines()))
    service = root / SERVICE
    service.parent.mkdir(parents=True)
    service.write_bytes(b'#!/bin/sh\necho STOCK\n')
    service.chmod(0o755)
    model = BootModel.prepare(root)
    kit = root / 'unpacked-kit'
    with ZipFile(args.archive) as bundle:
        bundle.extractall(kit)
    def cli(*params):
        result = subprocess.run(
            [sys.executable, '-I', str(kit / 'launch.py'), *params,
             '--simulator-root', str(root)], text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout)
    rev = cli('plan')['revision']
    cli('install', '--reviewed-revision', rev, '--accept-whole-overlay')
    shutil.rmtree(kit)  # Recovery must use the installed independent copy.
    return model


def dispatch(model):
    model.cold_boot()
    lines = subprocess.check_output([str(model.root / SERVICE), 'start'], text=True).splitlines()
    assert lines[-1] == 'STOCK', lines
    return json.loads(lines[0])


def off(root):
    # -I removes repo/PYTHONPATH dependency; cwd is deliberately outside the repo.
    result = subprocess.run([sys.executable, '-I', str(root / KIT / 'disable-rfid.py'),
                             '--simulator-root', str(root)], cwd=root,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value['state'] == 'disabled' and not (root / ENABLED).exists()
    assert not (root / CFG).exists()
    return value


def mesh(root):
    return rpc(root, 'objects/query', objects={'bed_mesh': ['profiles']})['status']['bed_mesh']['profiles']['default']['points']


def exercise(root, args, case, output):
    model = prepare(root, args)
    assert dispatch(model)['state'] == 'active'
    main = (root / tool.MAIN).read_bytes()
    module = root / tool.TARGETS[0]
    module_original = module.read_bytes()
    checks = []
    if case == 'syntax':
        module.write_bytes(b'def load_config(:\n')
    elif case == 'missing':
        module.unlink()
    elif case == 'bad-config':
        (root / CFG).write_bytes(b'[tracker_uid]\nstale_after: not-a-number\n')
    cfg_before = (root / CFG).read_bytes()
    if case == 'no-process':
        entry = root / 'klipper/klippy/klippy.py'
        original = entry.read_bytes()
        entry.write_bytes(b'raise SystemExit(73)\n')
        proc = subprocess.run([sys.executable, str(entry)], cwd=root, capture_output=True)
        assert proc.returncode == 73 and not (root / 'api.sock').exists()
        recovery = off(root)
        entry.write_bytes(original)
        checks.append('OFF works with Klippy exited before API socket creation')
    else:
        with klippy(root, case == 'api-unavailable') as info:
            if case in ('syntax', 'missing', 'bad-config'):
                assert info['state'] == 'error', info
                checks.append('actual Klippy error: ' + info['state_message'].splitlines()[0])
            elif case == 'api-unavailable':
                assert info['state'] == 'ready', info
                state = rpc(root, 'objects/query', objects={'tracker_uid': None})['status']['tracker_uid']
                assert state['state'] == 'unavailable' and 'API unavailable' in state['reason'], state
                assert 'tracker_uid/status' not in rpc(root, 'list_endpoints')['endpoints']
                checks.append('failed UID API registration leaves Klippy ready and RFID unavailable')
            else:
                assert info['state'] == 'ready', info
                status = rpc(root, 'tracker_uid/status')
                assert status['state'] == 'ready' and status['module_version'] == '0.6.0-auto-lookup-bench', status
                assert status['driver_version'] == '2.1.0.157'
                for channel, expected in ((0, '04112233'), (1, '04112233445566')):
                    rpc(root, 'bench_radio/scan', channel=channel)
                    for _ in range(100):
                        status = rpc(root, 'tracker_uid/status')
                        if status['channels'][str(channel)]['uid'] == expected:
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError(status)
                    checks.append('stock scan yields UID ' + expected)
                assert mesh(root) == [[.12,.13,.14],[.15,.16,.17],[.18,.19,.20]]
                assert (root / tool.DRIVER).read_bytes() == args.driver.read_bytes()
                checks.append('stock driver file and nine-point mesh unchanged')
            # Run OFF while the failed/ready Klippy process still exists. It does
            # not call that process, and cannot claim to unload its current state.
            recovery = off(root)
            checks.append('independent packaged OFF works while Klippy process exists')
        shutil.copyfile(root / 'process.log', output / (case + '-before.log'))
    assert (root / recovery['saved_config']).read_bytes() == cfg_before
    assert (root / tool.MAIN).read_bytes() == main
    assert off(root)['saved_config'] is None
    checks.append('OFF is idempotent; failed config retained; printer.cfg byte-identical')
    for attempt in range(2):
        assert dispatch(model)['state'] == 'disabled'
        with klippy(root, True) as info:  # API registration fault still enabled.
            assert info['state'] == 'ready', info
            assert 'tracker_uid' not in rpc(root, 'objects/list')['objects']
            assert 'tracker_uid/status' not in rpc(root, 'list_endpoints')['endpoints']
            assert mesh(root) == [[.12,.13,.14],[.15,.16,.17],[.18,.19,.20]]
            rpc(root, 'bench_radio/clear', channel=0)
            for _ in range(50):
                callbacks = rpc(root, 'objects/query', objects={'bench_radio': None})['status']['bench_radio']['stock_callbacks']
                if callbacks:
                    break
                time.sleep(.1)
            assert callbacks, 'Stock callback not received after OFF'
            if case == 'syntax' and attempt == 0:
                manual_print(root, root / 'jobs')
                checks.append('manual accounting without UID applies 1.250 g exactly once')
        shutil.copyfile(root / 'process.log', output / (case + '-off-' + str(attempt) + '.log'))
        assert (root / tool.MAIN).read_bytes() == main
        assert (root / tool.DRIVER).read_bytes() == args.driver.read_bytes()
        checks.append('disabled boot %d: ready, stock callbacks and calibration preserved' % (attempt + 1))
    if case == 'syntax':
        assert module.read_bytes() != module_original  # Success did not repair fault.
    if case == 'missing':
        assert not module.exists()
    return dict(case=case, checks=checks, recovery=recovery,
                config_sha256=hashlib.sha256(main).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'klipper', 'driver', 'dictionary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    assert hashlib.sha256(args.driver.read_bytes()).hexdigest() == DRIVER_HASH
    results = []
    try:
        for case in ('healthy', 'api-unavailable', 'syntax', 'missing', 'bad-config', 'no-process'):
            with tempfile.TemporaryDirectory(prefix='uid-off-', dir='/private/tmp') as tmp:
                results.append(exercise(Path(tmp) / 'sim', args, case, args.output))
                print('PASS', case, flush=True)
    finally:
        (args.output / 'results.json').write_text(json.dumps(dict(
            success=len(results) == 6, module_version='0.6.0-auto-lookup-bench',
            driver_version='2.1.0.157', driver_sha256=DRIVER_HASH,
            archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
            real_printer_used=False, rf_gpio_spi_mcu='simulated', cases=results), indent=2))


if __name__ == '__main__':
    main()
