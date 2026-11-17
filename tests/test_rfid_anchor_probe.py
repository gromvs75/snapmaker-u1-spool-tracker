"""The boot-dispatch experiment must never execute unreviewed service scripts."""
import json
import sys

import pytest

from dev.labs.uid_boot_bench import anchor_run as anchor

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX boot-policy laboratory')


@pytest.fixture
def probe(tmp_path):
    root = tmp_path.resolve() / 'owned bench'
    root.mkdir()
    (root / '.tracker-uid-simulator.json').write_text(json.dumps(anchor.tool.MARKER))
    (root / 'persistent').mkdir()
    probe = anchor.DispatchProbe(anchor.tool.Installer(root))
    probe.prepare_stock()
    return probe


def test_unreviewed_rcs_cannot_reach_shell(probe, monkeypatch):
    monkeypatch.setattr(anchor.subprocess, 'run', lambda *a, **kw: pytest.fail('shell invoked'))
    with pytest.raises(ValueError, match='Unexpected rcS'):
        probe.run(b'echo not reviewed')


@pytest.mark.parametrize('entry,contents', [
    ('S60klipper', '#!/bin/sh\necho foreign service\n'),
    ('S90lmd', '#!/bin/sh\necho changed approved name\n'),
])
def test_foreign_service_cannot_reach_shell(probe, monkeypatch, entry, contents):
    raw = b'# synthetic dispatcher for guard test\n'
    monkeypatch.setattr(anchor, 'RCS_SHA', anchor.tool.sha(raw))
    monkeypatch.setattr(anchor.subprocess, 'run', lambda *a, **kw: pytest.fail('shell invoked'))
    (probe.init / entry).write_text(contents)
    with pytest.raises(ValueError, match='Foreign init entry'):
        probe.run(raw)


def test_shell_paths_support_spaces_without_extra_commands(probe, monkeypatch):
    # Synthetic dispatch only; the process experiment separately pins actual U1 rcS.
    raw = b'for entry in /etc/init.d/S??*; do "$entry" start; done\n'
    monkeypatch.setattr(anchor, 'RCS_SHA', anchor.tool.sha(raw))
    assert probe.run(raw) == ['stock-service-probe']
    probe.place_volatile_probe()
    assert probe.run(raw) == ['dispatcher-probe', 'dispatcher-probe']
