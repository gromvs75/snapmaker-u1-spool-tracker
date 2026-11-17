"""Boot-policy trial with two real no-hardware Klipper/Moonraker processes.

Creates disposable localhost simulators. The source driver is the pinned 2.1.0.157
snapshot (same hash observed on U1); no reads from or requests to the user's U1.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'src'))
from dev.labs.uid_boot_bench.model import BootModel, PersistenceTrial, tool
from tracker_uid_client import UidClient, PrinterEndpoint

spec = importlib.util.spec_from_file_location('boot_multi_process', REPO / 'dev/labs/uid_multi_bench/run.py')
multi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(multi)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='rfid-boot-process-', dir='/private/tmp'))
    multi.ROOT = root
    source = REPO / 'output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157/klippy/extras/fm175xx_reader.py'
    driver_raw = source.read_bytes()
    assert tool.sha(driver_raw) == 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
    checks, printers, clients, trials = [], [], [], []
    result = {'success': False, 'root': str(root), 'checks': checks,
              'driver_sha256': tool.sha(driver_raw), 'scope': 'materialized boot policy, simulated RF/SPI/MCU'}

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS ' + label, flush=True)

    def stopped(p):
        p.stop_m()
        p.stop_k()

    def ready(p, client, *, previous=None, state='ready'):
        multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
        multi.wait(lambda: client.snapshot()['state'] == state and
                   (previous is None or client.snapshot()['epoch'] != previous))

    try:
        for pid, port in [('a', 18811), ('b', 18812)]:
            dest = root / pid
            dest.mkdir()
            (dest / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
            shutil.copytree(multi.SOURCE / 'klipper', dest / 'klipper',
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            p = multi.Printer(pid, port)
            printers.append(p)
            p.installer.rollback()
            (p.root / tool.DRIVER).write_bytes(driver_raw)
            model = BootModel.prepare(p.root)
            trial = PersistenceTrial(model)
            trials.append(trial)
            client = UidClient(PrinterEndpoint(pid, pid, p.url), poll_interval=.2, response_timeout=2)
            clients.append(client)
            client.start()
            p.start()
            ready(p, client, state='module_missing')
            check(pid + ': stock process ready without UID module')

            stopped(p)
            p.installer.install()
            p.start()
            ready(p, client)
            p.scan(2, '04AABBCC')
            multi.wait(lambda: client.snapshot()['channels']['2']['uid'] == '04AABBCC')
            check(pid + ': naive install initially reads UID with exact 2.1.0.157 driver')
            stopped(p)
            policy = model.cold_boot()
            p.start()
            multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'error')
            multi.wait(lambda: client.snapshot()['state'] != 'ready')
            error = p.http('/printer/info')['result']['state_message']
            (out / (pid + '-naive-boot-error.txt')).write_text(error)
            check(pid + ': naive cold boot causes real Klipper configuration error',
                  not policy['loadable'] and 'tracker_uid' in error and
                  all(c['uid'] is None for c in client.snapshot()['channels'].values()))
            stopped(p)
            p.installer.rollback()
            p.start()
            ready(p, client, state='module_missing')
            check(pid + ': explicit rollback recovers stock ready after missing module')

            stopped(p)
            trial.install(trial.plan(), accept_whole_overlay=True)
            p.start()
            ready(p, client)
            p.scan(1, '04112233445566')
            multi.wait(lambda: client.snapshot()['channels']['1']['uid'] == '04112233445566')
            epoch = client.snapshot()['epoch']
            check(pid + ': acknowledged persistence trial reads seven-byte UID')
            stopped(p)
            assert model.cold_boot()['loadable']
            p.start()
            ready(p, client, previous=epoch)
            check(pid + ': cold process boot reconnects with new epoch and no stale UID',
                  all(c['uid'] is None for c in client.snapshot()['channels'].values()))
            p.scan(3, '04CCDDEE')
            multi.wait(lambda: client.snapshot()['channels']['3']['uid'] == '04CCDDEE')
            callbacks = p.http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']
            check(pid + ': rescan after cold boot reaches UID channel and stock callback', bool(callbacks))

            stopped(p)
            trial.rollback()
            trial = PersistenceTrial(model)
            trials[-1] = trial
            try:
                trial.install(trial.plan(), accept_whole_overlay=True, fail_after=4)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Expected interruption after include commit')
            assert model.cold_boot()['loadable']
            p.start()
            ready(p, client)
            check(pid + ': interrupted installation after include still boots successfully')
            stopped(p)
            try:
                trial.rollback(fail_after=1)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Expected interruption after disabling include')
            assert model.cold_boot()['loadable']
            p.start()
            ready(p, client, state='module_missing')
            check(pid + ': interrupted rollback boots stock without stale UID')
            stopped(p)
            trial.rollback()
            assert model.cold_boot()['loadable']
            check(pid + ': resumed rollback restores exact original config and persistence',
                  (p.root / tool.MAIN).read_bytes() == p.before and not model.debug.exists())

            trial.install(trial.plan(), accept_whole_overlay=True)
            (p.root / tool.DRIVER).write_bytes(driver_raw + b'\n# simulated unknown firmware\n')
            model.cold_boot()
            p.start()
            multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
            status = p.http('/printer/objects/query?tracker_uid')['result']['status']['tracker_uid']
            check(pid + ': unknown driver disables observer while stock Klipper remains ready',
                  status['state'] == 'unavailable' and 'hash' in status['reason'].lower())
            stopped(p)
            (p.root / tool.DRIVER).write_bytes(driver_raw)
            trial.prepare_update()
            model.firmware_reset(clear_prepared=False)
            model.cold_boot()
            p.start()
            ready(p, client, state='module_missing')
            check(pid + ': pre-update removal survives loss of persistence marker',
                  (p.root / tool.MAIN).read_bytes() == p.before)
        check('two independent stock processes ready after completed rollback',
              all(c.snapshot()['state'] == 'module_missing' for c in clients))
        result['success'] = True
    finally:
        for c in clients:
            c.stop()
        cleanup_errors = []
        for n, p in enumerate(printers):
            stopped(p)
            try:
                if n < len(trials):
                    trials[n].rollback()
                p.installer.rollback()
            except Exception as e:
                cleanup_errors.append({'printer': p.pid, 'error': str(e)})
            for name in ('klippy', 'moonraker'):
                log = p.data / f'logs/{name}.log'
                if log.exists():
                    shutil.copy2(log, out / f'{p.pid}-{name}.log')
        result['processes_stopped'] = all(p.k is None and p.m is None for p in printers)
        result['cleanup_errors'] = cleanup_errors
        result['success'] = result['success'] and not cleanup_errors
        (out / 'results.json').write_text(json.dumps(result, indent=2))
    assert result['success'], result
    print(f'{len(checks)} process checks passed; owned processes stopped', flush=True)


if __name__ == '__main__':
    main()
