"""Session-only experiment: module and activating cfg share the volatile layer.

Not a persistent RFID solution or a physical-printer installer. An exact-name
glob makes absence of BOTH files harmless to Klipper; it does NOT protect
against loss of just the module while its activating cfg remains.
"""
import json
import re

from dev.labs.uid_boot_bench.model import BootModel, tool

CFG = 'klipper/klippy/extras/tracker_uid_boot.cfg'


# Exact autosave delimiter shared by the audited U1 and the bench parser.
AUTOSAVE = (b'\n#*# <---------------------- SAVE_CONFIG ---------------------->\n'
            b'#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n')


def matches_saved_probe_offset(expected, current):
    """Allow a rewritten numeric z_offset in an existing probe calibration only."""
    if current == expected:
        return True

    def parts(raw):
        if raw.count(AUTOSAVE) != 1:
            return None
        regular, saved = raw.split(AUTOSAVE)
        lines = saved.rstrip(b'\n').split(b'\n')
        section = b''
        offsets = 0
        for index, line in enumerate(lines):
            if line.startswith(b'#*# ['):
                section = line
            # ConfigParser serializes indented mesh rows with a tab. Keep every
            # coordinate and separator, ignoring just spaces vs tabs before a row.
            if section.startswith(b'#*# [bed_mesh ') and re.fullmatch(
                    rb'#\*# [ \t]+[-+0-9., eE]+', line):
                lines[index] = b'#*# \t' + line[4:].lstrip(b' \t')
            if section in (b'#*# [probe]', b'#*# [bltouch]') and re.fullmatch(rb'#\*# z_offset = [+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', line):
                lines[index] = None  # Distinct from any byte string in a file.
                offsets += 1
        if offsets:
            return regular.rstrip(b'\n'), lines
        return None

    baseline = parts(expected)
    return baseline is not None and baseline == parts(current)


class OptionalBootTrial:
    def __init__(self, model: BootModel):
        self.model = model
        self.base = model.base
        if any(c in str(model.root) for c in '\r\n[]*?'):
            raise ValueError('Unsupported characters in experiment root')
        pattern = self.base.path(CFG).with_name('[t]racker_uid_boot.cfg')
        self.block = ('\n# BEGIN TRACKER UID OPTIONAL BOOT\n[include ' + str(pattern) +
                      ']\n# END TRACKER UID OPTIONAL BOOT\n').encode()
        self.record = self.base.path('persistent/tracker-deployment/optional-plan.json')

    def configured_main(self, original):
        # Klipper owns everything below its SAVE_CONFIG delimiter.
        for line in original.splitlines(keepends=True):
            if line.rstrip(b'\r\n') == b'#*# <---------------------- SAVE_CONFIG ---------------------->':
                offset = original.index(line)
                return original[:offset] + self.block + original[offset:]
        return original + self.block

    def install(self, *, fail_after=None):
        self.model.stopped()
        if self.record.exists():
            raise ValueError('Recover previous optional trial first')
        # Original offline planner validates driver/include conflicts and absence
        # of old-layout files. Its transaction/layout is not modified or executed.
        self.base.plan()
        if self.base.path(CFG).exists():
            raise ValueError('Optional cfg destination already exists')
        old = self.base.path(tool.MAIN).read_bytes()
        if self.block in old:
            raise ValueError('Existing optional activation; manual review required')
        record = dict(schema=1, root=str(self.model.root),
                      firmware_identity=self.model.firmware_identity(),
                      main_before=tool.encode(old), block=tool.encode(self.block),
                      main_mode=self.base.path(tool.MAIN).stat().st_mode & 0o777,
                      module_sha256=tool.sha(tool.MODULE.read_bytes()), cfg_sha256=tool.sha(tool.CONFIG))
        record['revision'] = tool.sha(tool.canonical(record))
        tool.atomic(self.record, tool.canonical(record), 0o600)
        if fail_after == 0:
            raise RuntimeError('Interrupted after experiment record')
        for n, (name, content) in enumerate(((tool.TARGETS[0], tool.MODULE.read_bytes()),
                                            (CFG, tool.CONFIG), (tool.MAIN, self.configured_main(old))), 1):
            tool.atomic(self.base.path(name), content,
                        record['main_mode'] if name == tool.MAIN else 0o644)
            if fail_after == n:
                raise RuntimeError('Interrupted after optional layout write')

    def rollback(self, *, fail_after=None):
        self.model.stopped()
        if not self.record.exists():
            return 'no-trial'
        record = json.loads(self.record.read_text())
        revision = record.pop('revision')
        if (tool.sha(tool.canonical(record)) != revision or record.get('schema') != 1 or
                record.get('root') != str(self.model.root) or record.get('block') != tool.encode(self.block)):
            raise ValueError('Invalid optional experiment record')
        if record['firmware_identity'] != self.model.firmware_identity():
            raise ValueError('Firmware changed; review before rollback')
        # Validate everything before mutation. Missing volatile files are expected
        # after boot; changed files belong to someone else and are retained.
        for name, key in ((CFG, 'cfg_sha256'), (tool.TARGETS[0], 'module_sha256')):
            p = self.base.path(name)
            if p.exists() and tool.sha(p.read_bytes()) != record[key]:
                raise ValueError('Optional experiment file changed; do not delete')
        main = self.base.path(tool.MAIN)
        current = main.read_bytes()
        if 'rollback_main_after' not in record:
            if current.count(self.block) == 1:
                after = current.replace(self.block, b'', 1)
            elif current == tool.decode(record['main_before']):
                after = current
            else:
                raise ValueError('Activation changed; review other includes before removal')
            record.update(rollback_main_before=tool.encode(current), rollback_main_after=tool.encode(after))
            tool.atomic(self.record, tool.canonical(dict(record, revision=tool.sha(tool.canonical(record)))), 0o600)
        before, after = (tool.decode(record[k]) for k in ('rollback_main_before', 'rollback_main_after'))
        if current not in (before, after):
            raise ValueError('Config changed during optional rollback')
        # Preserve later edits. No old firmware/config tree is restored wholesale.
        if current != after:
            tool.atomic(main, after, main.stat().st_mode & 0o777)
        if fail_after == 1:
            raise RuntimeError('Interrupted after optional deactivation')
        for n, name in enumerate((CFG, tool.TARGETS[0]), 2):
            p = self.base.path(name)
            p.unlink(missing_ok=True)
            tool.sync_dir(p.parent)
            if fail_after == n:
                raise RuntimeError('Interrupted after optional removal')
        # Bytecode alone cannot activate this extra; remove only its known cache.
        cache = self.base.path('klipper/klippy/extras/__pycache__')
        if cache.exists():
            for p in cache.glob('tracker_uid.*.pyc'):
                self.base.path(p.relative_to(self.model.root).as_posix()).unlink()
            tool.sync_dir(cache)
        self.record.unlink()
        tool.sync_dir(self.record.parent)
        return 'rolled-back'
