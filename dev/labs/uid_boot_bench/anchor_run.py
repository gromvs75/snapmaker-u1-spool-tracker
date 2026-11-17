"""Bespok3d-style entrypoint loss: saved rcS + harmless stubs, two UID benches.

Does NOT execute Bespok3d enrollment/daemon, vendor S01/S60/S90, network/MCU
commands, or physical-printer services. Only rcS's dispatch loop is replayed,
with its sole /etc/init.d path redirected into an owned temporary directory.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / 'src')]
from dev.labs.uid_boot_bench.run import multi
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import SelectiveBootTrial, PACKAGE
from tracker_uid_client import UidClient, PrinterEndpoint

RCS_SHA = 'dc1615df9f2012b20b81ffad8e07e16293039ba7fd897854ca3646d6cfea0c0f'


class DispatchProbe:
    """Harmless stand-ins: record dispatch, never launch a daemon or modify Wi-Fi."""
    def __init__(self, base):
        self.base = base
        self.init = base.path('system/init.d')
        self.log = base.path('persistent/dispatch-probe.log')
        self.stock = '#!/bin/sh\nprintf "stock-service-probe\\n" >> ' + shlex.quote(str(self.log)) + '\n'
        self.dispatcher = '#!/bin/sh\nprintf "dispatcher-probe\\n" >> ' + shlex.quote(str(self.log)) + '\n'
        entry = shlex.quote(str(self.init / 'S99bespok3d'))
        self.redirect = '#!/bin/sh\n[ -x ' + entry + ' ] && exec ' + entry + ' "$@"\n' + self.stock.split('\n', 1)[1]

    def prepare_stock(self):
        self.init.mkdir(parents=True)
        tool.atomic(self.base.path('system/init.d/S90lmd'), self.stock.encode(), 0o755)

    def place_volatile_probe(self):
        tool.atomic(self.base.path('system/init.d/S99bespok3d'), self.dispatcher.encode(), 0o755)
        tool.atomic(self.base.path('system/init.d/S90lmd'), self.redirect.encode(), 0o755)

    def run(self, raw_rcs):
        if tool.sha(raw_rcs) != RCS_SHA:
            raise ValueError('Unexpected rcS; review source before shell replay')
        # No other script (especially a real vendor service) can enter this replay.
        expected = {'S90lmd': {self.stock, self.redirect}, 'S99bespok3d': {self.dispatcher}}
        for path in self.init.iterdir():
            checked = self.base.path(path.relative_to(self.base.root).as_posix())
            if checked.name not in expected or checked.read_text() not in expected[checked.name]:
                raise ValueError('Foreign init entry; do not execute')
        rewritten = raw_rcs.decode().replace('/etc/init.d', shlex.quote(str(self.init)))
        tool.atomic(self.log, b'')
        subprocess.run(['/bin/sh', '-c', rewritten], check=True, timeout=10,
                       cwd=self.base.root, capture_output=True, text=True)
        return self.log.read_text().splitlines()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    saved = json.loads((REPO / 'output/u1-rfid-readonly/boot-scripts.json').read_text())
    raw_rcs = saved['scripts']['/etc/init.d/rcS']['text'].encode()
    assert tool.sha(raw_rcs) == RCS_SHA
    driver = (REPO / 'output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157/klippy/extras/fm175xx_reader.py').read_bytes()
    assert tool.sha(driver) == 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'
    root = Path(tempfile.mkdtemp(prefix='rfid-anchor-', dir='/private/tmp'))
    multi.ROOT = root
    printers, clients, trials, checks = [], [], [], []
    result = dict(success=False, root=str(root), checks=checks, real_printer_access=False,
                  rcs_sha256=RCS_SHA, bespok_installer_executed=False,
                  dispatcher='harmless probe; not full Bespok3d', cold_boot='materialized policy model')

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS ' + label, flush=True)

    def stop(p):
        p.stop_m()
        p.stop_k()

    def ready(p, c, state):
        multi.wait(lambda: p.http('/printer/info')['result']['state'] == 'ready')
        multi.wait(lambda: c.snapshot()['state'] == state)

    try:
        for pid, port in [('a', 18841), ('b', 18842)]:
            dest = root / pid
            dest.mkdir()
            (dest / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
            shutil.copytree(multi.SOURCE / 'klipper', dest / 'klipper',
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            p = multi.Printer(pid, port)
            printers.append(p)
            p.installer.rollback()
            (p.root / tool.DRIVER).write_bytes(driver)
            probe = DispatchProbe(tool.Installer(p.root))
            probe.prepare_stock()
            model = BootModel.prepare(p.root)
            trial = SelectiveBootTrial(model)
            trials.append(trial)
            c = UidClient(PrinterEndpoint(pid, pid, p.url), poll_interval=.2, response_timeout=2)
            clients.append(c)
            c.start()
            trial.stage()
            trial.activate()  # explicit session setup, NOT a discovered boot hook
            p.start()
            ready(p, c, 'ready')
            p.scan(3, '04AABBCC')
            multi.wait(lambda: c.snapshot()['channels']['3']['uid'] == '04AABBCC')
            check(pid + ': explicit session setup reads UID before modeled reboot')
            stop(p)

            probe.place_volatile_probe()
            check(pid + ': rcS reaches redirected S90 and installed S99 before cleanup',
                  probe.run(raw_rcs) == ['dispatcher-probe', 'dispatcher-probe'])
            package = model.base.path(PACKAGE).read_bytes()
            for n in range(2):
                model.cold_boot()
                check(pid + f': no-debug boot {n + 1} loses init entry but retains persistent RFID package',
                      probe.run(raw_rcs) == ['stock-service-probe']
                      and not model.base.path('system/init.d/S99bespok3d').exists()
                      and model.base.path(PACKAGE).read_bytes() == package
                      and not model.debug.exists())
                p.start()
                ready(p, c, 'module_missing')
                check(pid + f': stock Klipper remains ready with no RFID or stale UID after boot {n + 1}',
                      all(ch['uid'] is None for ch in c.snapshot()['channels'].values()))
                stop(p)

            # Positive control ONLY in this disposable model. Not proposed for U1.
            model.debug.write_bytes(b'LAB POSITIVE CONTROL ONLY\n')
            probe.place_volatile_probe()
            model.base.path('system/unrelated-change').write_bytes(b'also retained\n')
            model.cold_boot()
            check(pid + ': debug control retains entrypoint AND unrelated system changes',
                  probe.run(raw_rcs) == ['dispatcher-probe', 'dispatcher-probe']
                  and model.base.path('system/unrelated-change').exists())
            model.debug.unlink()
            model.cold_boot()
            check(pid + ': removing modeled debug restores stock dispatch without autoload',
                  probe.run(raw_rcs) == ['stock-service-probe']
                  and not model.base.path('system/unrelated-change').exists())

            # Explicit activation still works, but it is not autonomous boot persistence.
            assert trial.activate()['state'] == 'active'
            p.start()
            ready(p, c, 'ready')
            p.scan(1, '04112233445566')
            multi.wait(lambda: c.snapshot()['channels']['1']['uid'] == '04112233445566')
            check(pid + ': explicit post-boot activation restores RFID without firmware persistence')
            stop(p)
            trial.rollback()
            model.cold_boot()
            p.start()
            ready(p, c, 'module_missing')
            check(pid + ': final rollback restores stock config and leaves no debug marker',
                  (p.root / tool.MAIN).read_bytes() == p.before and not model.debug.exists())
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
    print(f'{len(checks)} anchor checks passed; owned processes stopped', flush=True)


if __name__ == '__main__':
    main()
