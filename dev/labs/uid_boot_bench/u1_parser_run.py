"""Exercise the pinned vendor parser and packaged UID module in a disposable file bench."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dev.labs.uid_boot_bench.model import BootModel, tool
from dev.labs.uid_boot_bench.debug_loader import KIT, SERVICE
from dev.labs.uid_boot_bench.optional import CFG

PARSER = '36163852a7f42dc1af1a1166f745456aad66b40cf25a97106ef849e050be97fc'
DRIVER = 'ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def simulate_tag(reader, fm):
    # Supply only the pins and card replies, keeping stock channel selection,
    # activation and the module's callback chain intact.
    prefix = '_FM175XXReader__'
    pin = SimpleNamespace(set_value=lambda level: None)
    reader.extra_ch_1, reader.soc_ch_2 = 0, 2
    card = fm.Fm175xxPiccMetaData()
    card.ATQA[0] = 0
    for index, value in enumerate((4, 17, 34, 51)):
        card.UID[index] = value
    card.BCC[0] = 4 ^ 17 ^ 34 ^ 51
    card.SAK[0] = 0
    for name, value in dict(rf_1_pin=pin, rf_2_pin=pin, picc_a=card,
                            reader_a_wakeup=lambda: 0, reader_a_anticoll=lambda level: 0,
                            reader_a_select=lambda level: 0).items():
        setattr(reader, prefix + name, value)
    getattr(reader, prefix + 'select_channel')(2)
    assert getattr(reader, prefix + 'reader_a_activate')() == fm.FM175XX_OK
    getattr(reader, prefix + 'card_info_deal_cb')(2, fm.FM175XX_CARD_INFO_READ, 0, 0, [])


def exercise(kit, root, parser, driver, checks):
    for layout in ('klipper/klippy/extras', 'printer_data/config', 'system/init.d'):
        (root / layout).mkdir(parents=True)
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(tool.MARKER))
    shutil.copyfile(driver, root / tool.DRIVER)
    main = root / tool.MAIN
    original = ('[include fluidd.cfg]\n[include xyz_offset_calibration.cfg]\n'
                + parser.AUTOSAVE_HEADER + '#*# [probe]\n#*# z_offset = 1.25\n'
                '#*#\n#*# [bed_mesh default]\n#*# points = 0.12, 0.13\n#*#   0.14, 0.15\n')
    main.write_text(original)
    for name in ('fluidd.cfg', 'xyz_offset_calibration.cfg'):
        main.with_name(name).write_text('# bench fixture\n')
    stock = b'#!/bin/sh\necho STOCK\n'
    service = root / SERVICE
    service.write_bytes(stock)
    service.chmod(0o755)
    model = BootModel.prepare(root)

    def cli(action, *flags, launcher=kit / 'launch.py'):
        out = subprocess.check_output([sys.executable, '-I', str(launcher), action,
                                      '--simulator-root', str(root), *flags], text=True)
        return json.loads(out)

    def boot():
        model.cold_boot()
        lines = subprocess.check_output([str(service), 'start'], text=True).splitlines()
        assert lines[-1] == 'STOCK', lines
        return json.loads(lines[0])

    fm = load('fm_bench', root / tool.DRIVER)
    events, commands = {}, {}
    fake_gcode = SimpleNamespace(register_command=lambda name, cb, **kw: commands.update({name: cb}),
                                 error=ValueError)
    services = dict(gcode=fake_gcode,
                    webhooks=SimpleNamespace(register_endpoint=lambda *args: None))
    printer = SimpleNamespace(lookup_object=services.get, get_start_args=lambda: {'config_file': str(main)},
                              get_reactor=lambda: SimpleNamespace(register_async_callback=lambda fn: fn(0)),
                              register_event_handler=events.__setitem__)
    config = parser.PrinterConfig(printer)

    def read(active, offset):
        cfg = config.read_main_config()
        assert cfg.has_section('tracker_uid') == active
        assert cfg.getsection('probe').getfloat('z_offset') == offset
        mesh = cfg.getsection('bed_mesh default').get('points')
        assert mesh.splitlines() == ['0.12, 0.13', '0.14, 0.15']
        if active:
            reader = fm.FM175XXReader.__new__(fm.FM175XXReader)
            reader.register_cb_2_card_info_deal(lambda *args: None)
            services['fm175xx_reader'] = reader
            uid = load('tracker_uid_bench', root / tool.TARGETS[0]).load_config(cfg.getsection('tracker_uid'))
            events['klippy:connect']()
            events['klippy:ready']()
            state = uid.get_status()
            assert (state['state'], state['driver_version']) == ('ready', '2.1.0.157'), state
            simulate_tag(reader, fm)
            assert uid.get_status()['channels']['2']['uid'] == '04112233'
            events['klippy:disconnect']()

    rev = cli('plan')['revision']
    cli('install', '--reviewed-revision', rev, '--accept-whole-overlay')
    read(False, 1.25)
    checks.append('optional include absent; original offset 1.25')
    assert boot()['state'] == 'active'
    read(True, 1.25)
    checks.append('packaged module ready with pinned driver; simulated UID 04112233 on channel 2')
    config.set('probe', 'z_offset', '1.42')
    before = main.read_bytes()
    commands['SAVE_CONFIG'](SimpleNamespace(get_int=lambda name, default: 0))
    assert any(p.read_bytes() == before for p in main.parent.glob('printer-*.cfg'))
    read(True, 1.42)
    checks.append('vendor SAVE_CONFIG RESTART=0 wrote 1.42 and backed up old config')
    activation = boot()
    checks.append(activation)
    read(activation['state'] == 'active', 1.42)
    if activation['state'] == 'active':
        before_edit = main.read_bytes()
        main.write_bytes(before_edit.replace(b'#*# [probe]', b'#*# [tracker_uid]'))
        assert boot()['reason'] == 'configuration-changed'
        main.write_bytes(before_edit.replace(b'0.14, 0.15', b'0.24, 0.15'))
        assert boot()['reason'] == 'configuration-changed'
        main.write_bytes(before_edit)
        assert boot()['state'] == 'active'
        checks.append('unrelated autosave section rejected')
    assert cli('rollback', launcher=root / KIT / 'launch.py')['state'] == 'rolled-back'
    read(False, 1.42)
    assert service.read_bytes() == stock and not model.debug.exists()
    assert not any((root / path).exists() for path in (CFG, tool.TARGETS[0]))
    assert 'TRACKER UID' not in main.read_text()
    checks.append('stock service and config restored with new offset 1.42')
    return activation


def main():
    args = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'parser', 'driver'):
        args.add_argument(name, type=Path)
    paths = args.parse_args()
    assert tool.sha(paths.parser.read_bytes()) == PARSER and tool.sha(paths.driver.read_bytes()) == DRIVER
    sys.dont_write_bytecode = True
    sys.modules['coded_exception'] = SimpleNamespace(CodedException=type('CodedException', (Exception,), {}))
    for name in ('spidev', 'gpiod'):
        sys.modules[name] = ModuleType(name)
    parser = load('u1_configfile', paths.parser)
    if not hasattr(os, 'fdatasync'):
        # macOS host substitute for the vendor Linux syscall; keep its file/rename code.
        parser.os = SimpleNamespace(**{**vars(os), 'fdatasync': os.fsync})
    checks = []
    with TemporaryDirectory() as directory:
        work = Path(directory).resolve()
        kit = work / 'kit'
        with ZipFile(paths.archive) as archive:
            archive.extractall(kit)
        result = exercise(kit, work / 'model', parser, paths.driver, checks)
    print(json.dumps(dict(parser=PARSER, archive=tool.sha(paths.archive.read_bytes()),
                          fdatasync_substitute=not hasattr(os, 'fdatasync'), checks=checks), indent=2))
    return int(result['state'] != 'active')


if __name__ == '__main__':
    sys.exit(main())
