"""Two process benches: persisted init wrapper, optional UID config, offline recovery.

No vendor init or MCU commands run. Cold-boot cleanup is a materialized model;
the stock S60 stand-in records dispatch, then the runner starts no-hardware Klipper.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / 'src')]
from dev.labs.uid_boot_bench.run import multi
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.debug_loader import DebugLoaderTrial, SERVICE, KIT
from dev.labs.uid_boot_bench.selective import PACKAGE, CFG
from tracker_uid_client import UidClient, PrinterEndpoint


class GuardedPrinter(multi.Printer):
    def start_k(self):
        # Invoke the INSTALLED wrapper from the modeled filesystem, not activate().
        result = subprocess.run([str(self.root / SERVICE), 'start'], capture_output=True,
                                text=True, timeout=20)
        self.dispatch = result.stdout.splitlines()
        if result.returncode or not self.dispatch or self.dispatch[-1] != 'BENCH_STOCK_START':
            raise RuntimeError('Startup guard refused: ' + result.stdout + result.stderr)
        super().start_k()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='rfid-debug-loader-', dir='/private/tmp'))
    multi.ROOT = root
    driver = (REPO / 'output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157/klippy/extras/fm175xx_reader.py').read_bytes()
    assert tool.sha(driver) == 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
    printers, clients, trials, checks = [], [], [], []
    result = dict(success=False, root=str(root), checks=checks, real_printer_access=False,
                  global_persistence='temporary model only', hardware_rfid=False,
                  boot_anchor='persisted wrapper against stock-service stand-in; no vendor init/MCU')

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS ' + label, flush=True)

    def stop(p):
        p.stop_m()
        p.stop_k()

    def ready(p, c, state='ready'):
        multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
        multi.wait(lambda: c.snapshot()['state'] == state)

    def recovery(p):
        command = [sys.executable, '-I', str(p.root / KIT / 'launch.py'), 'rollback',
                   '--simulator-root', str(p.root)]
        r = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=20)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    try:
        for pid, port in [('a', 18851), ('b', 18852)]:
            dest = root / pid
            dest.mkdir()
            (dest / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
            shutil.copytree(multi.SOURCE / 'klipper', dest / 'klipper',
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            p = GuardedPrinter(pid, port)
            printers.append(p)
            p.installer.rollback()
            (p.root / tool.DRIVER).write_bytes(driver)
            service = p.root / SERVICE
            service.parent.mkdir(parents=True)
            service.write_bytes(b'#!/bin/sh\nprintf "BENCH_STOCK_START\\n"\n')
            service.chmod(0o755)
            model = BootModel.prepare(p.root)
            trial = DebugLoaderTrial(model)
            trials.append(trial)
            client = UidClient(PrinterEndpoint(pid, pid, p.url), poll_interval=.2, response_timeout=2)
            clients.append(client)
            client.start()
            trial.install(trial.plan(), accept_whole_overlay=True)
            check(pid + ': install leaves activation absent until guarded start', not (p.root / CFG).exists())
            for n in range(2):
                model.cold_boot()
                p.start()
                ready(p, client)
                check(pid + f': boot {n+1} invokes independent guard before stock startup',
                      json.loads(p.dispatch[0])['state'] == 'active')
                check(pid + f': boot {n+1} begins without stale UID',
                      all(ch['uid'] is None for ch in client.snapshot()['channels'].values()))
                uid = '04AABBCC' if n == 0 else '04112233445566'
                p.scan(n, uid)
                multi.wait(lambda: client.snapshot()['channels'][str(n)]['uid'] == uid)
                callbacks = p.http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']
                check(pid + f': boot {n+1} reads UID and preserves stock reader callback', bool(callbacks))
                stop(p)

            # Repair a lost owned module before loading its config.
            (p.root / tool.TARGETS[0]).unlink()
            p.start()
            ready(p, client)
            check(pid + ': missing owned module restored before Klipper', (p.root / CFG).exists())
            epoch = client.snapshot()['epoch']
            p.http('/printer/restart', {})
            multi.wait(lambda: client.snapshot()['state'] == 'ready' and client.snapshot()['epoch'] != epoch)
            check(pid + ': ordinary Klipper restart has fresh epoch',
                  all(ch['uid'] is None for ch in client.snapshot()['channels'].values()))
            connections = client.snapshot()['connections']
            p.stop_m()
            multi.wait(lambda: client.snapshot()['state'] == 'offline')
            p.start_m()
            multi.wait(lambda: client.snapshot()['state'] == 'ready' and client.snapshot()['connections'] > connections)
            check(pid + ': Moonraker reconnect restores UID channel')
            stop(p)

            package = (p.root / PACKAGE).read_bytes()
            (p.root / PACKAGE).write_bytes(b'corrupt fixture')
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': corrupt package disables RFID while Klipper stays ready',
                  json.loads(p.dispatch[0])['reason'] == 'package-invalid' and not (p.root / CFG).exists())
            stop(p)
            (p.root / PACKAGE).write_bytes(package)  # explicit fixture-owner repair
            p.start()
            ready(p, client)
            check(pid + ': reviewed package repair restores guarded UID startup')
            stop(p)

            # Keep .debug but change modeled firmware: guard withdraws RFID.
            new_fw = model.lower / 'system/update-fixture'
            new_fw.write_bytes(b'new firmware identity')
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': changed firmware disables module without old automatic reinstall',
                  json.loads(p.dispatch[0])['reason'] == 'firmware-changed')
            stop(p)
            new_fw.unlink()  # restore test fixture, not a real firmware downgrade

            if pid == 'a':
                model.debug.unlink()  # modeled updater/removal, no physical printer
                model.cold_boot()
                p.start()
                ready(p, client, 'module_missing')
                check(pid + ': lost debug boots stock with inert optional include',
                      len(p.dispatch) == 1 and not (p.root / CFG).exists())
                stop(p)
            else:
                foreign = model.base.path('system/user-setting')
                foreign.write_bytes(b'preserve this')
                state = recovery(p)
                check(pid + ': independent rollback preserves foreign setting and debug',
                      state['state'] == 'rfid-removed-persistence-retained' and model.debug.exists()
                      and foreign.read_bytes() == b'preserve this')
                p.start()
                ready(p, client, 'module_missing')
                check(pid + ': stock starts after RFID-only rollback with retained persistence')
                stop(p)
                foreign.unlink()  # only bench owner removes its known fixture
            check(pid + ': independent final recovery restores exact original config',
                  recovery(p)['state'] == 'rolled-back'
                  and (p.root / tool.MAIN).read_bytes() == p.before and not model.debug.exists())
            model.cold_boot()
            p.start()
            ready(p, client, 'module_missing')
            check(pid + ': final stock boot has no RFID or stale tag',
                  all(ch['uid'] is None for ch in client.snapshot()['channels'].values()))
            stop(p)
        result['success'] = True
    finally:
        for c in clients:
            c.stop()
        errors = []
        for n, p in enumerate(printers):
            stop(p)
            try:
                if n < len(trials):
                    trials[n].rollback()
                assert (p.root / tool.MAIN).read_bytes() == p.before
                assert not (p.root / 'persistent/.debug').exists()
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
    print(f'{len(checks)} checks passed; owned processes stopped', flush=True)


if __name__ == '__main__':
    main()
