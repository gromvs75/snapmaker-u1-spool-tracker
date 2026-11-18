"""Exercise the distributed ZIP and the supplied bench Klipper config parser."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dev.labs.uid_boot_bench.debug_loader import SERVICE, KIT
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.selective import PACKAGE


def run(archive, driver, parser_path):
    spec = importlib.util.spec_from_file_location('bench_configfile', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    reader = parser.ConfigFileReader()
    checks = []

    def check(label, success):
        if not success:
            raise AssertionError(label)
        checks.append(label)

    with TemporaryDirectory() as tmp:
        work = Path(tmp).resolve()
        kit = work / 'unpacked'
        with ZipFile(archive) as bundle:
            bundle.extractall(kit)
        root = work / 'simulator'
        for name in ('klipper/klippy/extras', 'printer_data/config', 'system/init.d'):
            (root / name).mkdir(parents=True)
        (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
        shutil.copyfile(driver, root / tool.DRIVER)
        original = ('[include fluidd.cfg]\n[include xyz_offset_calibration.cfg]\n'
                    + parser.AUTOSAVE_HEADER + '#*# [probe]\n#*# z_offset = 1.25\n').encode()
        main = root / tool.MAIN
        main.write_bytes(original)
        for name in ('fluidd.cfg', 'xyz_offset_calibration.cfg'):
            main.with_name(name).write_text('# fixture\n')
        service = root / SERVICE
        stock = b'#!/bin/sh\necho STOCK\n'
        service.write_bytes(stock)
        service.chmod(0o755)
        model = BootModel.prepare(root)

        def cli(action, *flags, launcher=kit / 'launch.py', ok=True):
            result = subprocess.run([sys.executable, '-I', str(launcher), action,
                                     '--simulator-root', str(root), *flags], cwd=work,
                                    capture_output=True, text=True, timeout=15)
            if (result.returncode == 0) != ok:
                raise RuntimeError(result.stdout + result.stderr)
            return json.loads(result.stdout)

        def parsed():
            regular, autosave = parser.ConfigAutoSave._find_autosave_data(None, main.read_text())
            config = reader.build_fileconfig_with_includes(regular, str(main))
            check('calibration retained', 'z_offset = 1.25' in autosave)
            return config.has_section('tracker_uid')

        plan = cli('plan')
        cli('install', '--reviewed-revision', 'stale', '--accept-whole-overlay', ok=False)
        check('stale plan leaves stock untouched', service.read_bytes() == stock and main.read_bytes() == original)
        cli('install', '--reviewed-revision', plan['revision'], '--accept-whole-overlay')
        check('optional include with RFID disabled parses', not parsed())
        shutil.rmtree(kit)
        for _ in range(2):
            model.cold_boot()
            lines = subprocess.check_output([str(service), 'start'], text=True, cwd=work).splitlines()
            check('guarded start enables RFID', json.loads(lines[0])['state'] == 'active'
                  and lines[-1] == 'STOCK' and parsed())
        (root / PACKAGE).write_text('{}')
        lines = subprocess.check_output([str(service), 'start'], text=True, cwd=work).splitlines()
        check('damaged payload leaves stock config usable', json.loads(lines[0])['state'] == 'disabled'
              and lines[-1] == 'STOCK' and not parsed())
        restored = cli('rollback', launcher=root / KIT / 'launch.py')
        check('independent recovery', restored['state'] == 'rolled-back' and not model.debug.exists()
              and main.read_bytes() == original and service.read_bytes() == stock)
    return dict(checks=checks, parser_sha256=tool.sha(parser_path.read_bytes()),
                archive_sha256=tool.sha(archive.read_bytes()), driver_sha256=tool.sha(driver.read_bytes()))


if __name__ == '__main__':
    opts = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'driver', 'parser'):
        opts.add_argument(name, type=Path)
    args = opts.parse_args()
    print(json.dumps(run(args.archive, args.driver, args.parser), indent=2))
