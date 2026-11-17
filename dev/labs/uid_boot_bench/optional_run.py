"""Two localhost Klipper/Moonraker pairs: optional RFID activation after layer loss."""
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
from dev.labs.uid_boot_bench.optional import OptionalBootTrial, CFG
from tracker_uid_client import UidClient, PrinterEndpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='rfid-optional-', dir='/private/tmp'))
    multi.ROOT = root
    source = REPO / 'output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157/klippy/extras/fm175xx_reader.py'
    driver = source.read_bytes()
    assert tool.sha(driver) == 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
    printers, clients, trials, checks = [], [], [], []
    result = dict(success=False, root=str(root), checks=checks, real_printer_access=False,
                  automatic_reinstall=False, persistence_enabled=False)

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS ' + label, flush=True)

    def stop(p):
        p.stop_m()
        p.stop_k()

    def ready(p, client, state):
        multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
        multi.wait(lambda: client.snapshot()['state'] == state)

    try:
        for pid, port in [('a', 18821), ('b', 18822)]:
            dest = root / pid
            dest.mkdir()
            (dest / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
            shutil.copytree(multi.SOURCE / 'klipper', dest / 'klipper',
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            p = multi.Printer(pid, port)
            printers.append(p)
            p.installer.rollback()
            (p.root / tool.DRIVER).write_bytes(driver)
            model = BootModel.prepare(p.root)
            trial = OptionalBootTrial(model)
            trials.append(trial)
            client = UidClient(PrinterEndpoint(pid, pid, p.url), poll_interval=.2, response_timeout=2)
            clients.append(client)
            client.start()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': stock Klipper ready')

            stop(p)
            trial.install()
            p.start()
            ready(p, client, 'ready')
            p.scan(3, '04AABBCC')
            multi.wait(lambda: client.snapshot()['channels']['3']['uid'] == '04AABBCC')
            check(pid + ': optional cfg activates UID without global persistence', not model.debug.exists())
            stop(p)
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': layer loss boots stock Klipper and invalidates UID',
                  not model.base.path(CFG).exists() and not model.base.path(tool.TARGETS[0]).exists()
                  and trial.block in model.base.path(tool.MAIN).read_bytes()
                  and all(c['uid'] is None for c in client.snapshot()['channels'].values()))
            stop(p)
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': repeated cold boot stays stock with no implicit reinstall')
            stop(p)
            trial.rollback()
            check(pid + ': explicit cleanup restores original config', model.base.path(tool.MAIN).read_bytes() == p.before)

            try:
                trial.install(fail_after=2)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Expected interruption')
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': interruption before activation leaves stock Klipper ready')
            stop(p)
            model.cold_boot()
            trial.rollback()
            try:
                trial.install(fail_after=3)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Expected interruption')
            p.start()
            ready(p, client, 'ready')
            check(pid + ': interruption after activation still has complete module and cfg')

            # Adversarial case: unlike whole-layer loss, deleting just the module
            # still breaks startup. Keep this limitation demonstrated, not hidden.
            stop(p)
            model.base.path(tool.TARGETS[0]).unlink()
            p.start()
            multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'error')
            error = p.http('/printer/info')['result']['state_message']
            (out / (pid + '-module-only-loss.txt')).write_text(error)
            check(pid + ': module-only deletion remains a diagnosed startup error', 'tracker_uid' in error)
            stop(p)
            trial.rollback()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': explicit rollback recovers from module-only deletion')

            stop(p)
            trial.install()
            p.start()
            ready(p, client, 'ready')
            p.scan(1, '04112233445566')
            multi.wait(lambda: client.snapshot()['channels']['1']['uid'] == '04112233445566')
            check(pid + ': explicit re-enable reads seven-byte UID again')
            stop(p)
            model.firmware_reset()
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': modeled vendor marker reset leaves stock config and no UID activation',
                  model.base.path(tool.MAIN).read_bytes() == p.before)
        check('both printers remain independent and stock ready',
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
    print(f'{len(checks)} optional-boot checks passed; owned processes stopped', flush=True)


if __name__ == '__main__':
    main()
