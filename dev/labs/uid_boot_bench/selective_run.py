"""Two process benches with an EXPLICIT test-runner pre-start hook, not U1 init."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / 'src')]
from dev.labs.uid_boot_bench.run import multi
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import SelectiveBootTrial, PACKAGE, CFG
from tracker_uid_client import UidClient, PrinterEndpoint


class HookedPrinter(multi.Printer):
    trial = None
    last_activation = None

    def start_k(self):
        # This is the missing real-device boot anchor, supplied by the TEST RUNNER.
        # Exceptions prevent startup; no service is stopped/restarted implicitly.
        if self.trial is not None:
            self.last_activation = self.trial.activate()
        super().start_k()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='rfid-selective-', dir='/private/tmp'))
    multi.ROOT = root
    source = REPO / 'output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157/klippy/extras/fm175xx_reader.py'
    driver = source.read_bytes()
    assert tool.sha(driver) == 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
    printers, clients, trials, checks = [], [], [], []
    result = dict(success=False, root=str(root), checks=checks, real_printer_access=False,
                  boot_anchor='test-runner-only; no U1 persistent hook established',
                  global_persistence=False, hardware_rfid=False)

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS ' + label, flush=True)

    def stop(p):
        p.stop_m()
        p.stop_k()

    def ready(p, client, state='ready'):
        multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
        multi.wait(lambda: client.snapshot()['state'] == state)

    try:
        for pid, port in [('a', 18831), ('b', 18832)]:
            dest = root / pid
            dest.mkdir()
            (dest / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
            shutil.copytree(multi.SOURCE / 'klipper', dest / 'klipper',
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            p = HookedPrinter(pid, port)
            printers.append(p)
            p.installer.rollback()
            (p.root / tool.DRIVER).write_bytes(driver)
            model = BootModel.prepare(p.root)
            trial = SelectiveBootTrial(model)
            trials.append(trial)
            client = UidClient(PrinterEndpoint(pid, pid, p.url), poll_interval=.2, response_timeout=2)
            clients.append(client)
            client.start()

            trial.stage()
            model.cold_boot()
            p.trial = trial
            p.start()
            ready(p, client)
            p.scan(3, '04AABBCC')
            multi.wait(lambda: client.snapshot()['channels']['3']['uid'] == '04AABBCC')
            check(pid + ': runner pre-start hook loads persistent package after layer cleanup',
                  p.last_activation['state'] == 'active' and not model.debug.exists())

            epoch = client.snapshot()['epoch']
            p.http('/printer/restart', {})
            multi.wait(lambda: client.snapshot()['state'] == 'ready' and client.snapshot()['epoch'] != epoch)
            check(pid + ': Klipper restart creates fresh epoch with no stale UID',
                  all(c['uid'] is None for c in client.snapshot()['channels'].values()))

            for n in range(2):
                epoch = client.snapshot()['epoch']
                stop(p)
                model.base.path('system/unrelated-session.conf').write_text('do not retain\n')
                model.cold_boot()
                p.trial = SelectiveBootTrial(BootModel(p.root))
                p.start()
                ready(p, client)
                multi.wait(lambda: client.snapshot()['epoch'] != epoch)
                check(pid + f': cold boot {n + 1} restores only RFID and clears old observations',
                      not model.base.path('system/unrelated-session.conf').exists()
                      and not model.debug.exists()
                      and all(c['uid'] is None for c in client.snapshot()['channels'].values()))
                p.scan(1, '04112233445566')
                multi.wait(lambda: client.snapshot()['channels']['1']['uid'] == '04112233445566')
                callbacks = p.http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']
                check(pid + f': cold boot {n + 1} reads seven-byte tag and preserves stock callback', bool(callbacks))

            connections = client.snapshot()['connections']
            p.stop_m()
            multi.wait(lambda: client.snapshot()['state'] == 'offline')
            check(pid + ': transport loss invalidates observations',
                  all(c['uid'] is None for c in client.snapshot()['channels'].values()))
            p.start_m()
            ready(p, client)
            multi.wait(lambda: client.snapshot()['connections'] > connections)
            p.scan(0, '04010203')
            multi.wait(lambda: client.snapshot()['channels']['0']['uid'] == '04010203')
            check(pid + ': reconnect restores subscription and new scans')

            stop(p)
            model.base.path(tool.TARGETS[0]).unlink()
            p.start()
            ready(p, client)
            check(pid + ': pre-start validation repairs missing module before activating cfg',
                  model.base.path(tool.TARGETS[0]).read_bytes() == tool.MODULE.read_bytes())

            stop(p)
            package = model.base.path(PACKAGE).read_bytes()
            model.base.path(PACKAGE).write_bytes(b'corrupt package')
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': corrupt persistent package leaves stock Klipper ready',
                  p.last_activation['reason'] == 'package-invalid')
            stop(p)
            model.base.path(PACKAGE).write_bytes(package)  # explicit bench-owner repair

            lower_driver = model.lower / 'klipper' / tool.DRIVER.removeprefix('klipper/')
            lower_driver.write_bytes(driver + b'\n# modeled new firmware\n')
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': firmware change disables old package instead of reinstalling it',
                  p.last_activation['reason'] == 'firmware-changed')
            stop(p)
            lower_driver.write_bytes(driver)  # explicit reset of the test fixture only
            model.cold_boot()

            # A permanent payload is not a boot hook. Exercise this counterexample.
            p.trial = None
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': without runner hook persistent payload alone does not load RFID',
                  model.base.path(PACKAGE).exists() and not model.base.path(CFG).exists())
            stop(p)
            p.trial = trial

            for boundary in range(3):
                model.cold_boot()
                try:
                    trial.activate(fail_after=boundary)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Expected interrupted activation')
                # Next boot invocation retries from persistent evidence, no RAM state.
                p.trial = SelectiveBootTrial(BootModel(p.root))
                p.start()
                ready(p, client)
                check(pid + f': fresh pre-start invocation recovers activation boundary {boundary}')
                stop(p)

            try:
                trial.rollback(fail_after=0)
            except RuntimeError:
                pass
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': interrupted rollback never reactivates on cold boot')
            stop(p)
            trial.rollback()
            trial.stage()
            model.firmware_reset()
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': modeled vendor config reset does not restore stale user configuration',
                  p.last_activation['reason'] == 'configuration-changed'
                  and model.base.path(tool.MAIN).read_bytes() == p.before)
            stop(p)
            trial.rollback()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': completed rollback boots stock and removes persistent activation',
                  not model.base.path(PACKAGE).exists())
        check('two independent stock Klipper/Moonraker pairs ready after rollback',
              all(c.snapshot()['state'] == 'module_missing' for c in clients))
        result['success'] = True
    finally:
        for client in clients:
            client.stop()
        errors = []
        for n, p in enumerate(printers):
            stop(p)
            try:
                if n < len(trials):
                    trials[n].rollback()
                assert (p.root / tool.MAIN).read_bytes() == p.before
            except Exception as exc:
                errors.append(dict(printer=p.pid, error=str(exc)))
            for name in ('klippy', 'moonraker'):
                log = p.data / f'logs/{name}.log'
                if log.exists():
                    shutil.copy2(log, out / f'{p.pid}-{name}.log')
        result.update(cleanup_errors=errors, processes_stopped=all(p.k is None and p.m is None for p in printers))
        result['success'] = result['success'] and not errors
        (out / 'results.json').write_text(json.dumps(result, indent=2))
    assert result['success'], result
    print(f'{len(checks)} selective-boot checks passed; owned processes stopped', flush=True)


if __name__ == '__main__':
    main()
