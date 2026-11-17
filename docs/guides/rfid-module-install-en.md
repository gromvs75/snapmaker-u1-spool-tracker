# RFID module installation and rollback: bench kit

Status: **offline rehearsal candidate, not approval to install on a real U1**.
The kit makes no SSH/printer requests, controls no services and never writes the
stock reader driver. Writes require a marked simulator root. Do not manufacture
that marker on a real printer to bypass the restriction.

**2026-11-17 update:** the inspected stock U1 2.1.0.157 discards the system
overlay at boot while retaining user configuration. A simple file installation
can leave `[tracker_uid]` configured with its Python module missing, preventing
Klipper startup. Two process benches reproduced this. Do not enable `/oem/.debug`
using this guide: it persists the entire system overlay. Physical deployment is
not ready. See the [boot-policy experiment](../development/rfid-boot-lifecycle-2026-11-17.md).

Bespok3d was also reviewed: its installer creates `.debug` and modifies system
init scripts. It does not provide a ready-made no-debug solution. No supported
persistent invocation point for our loader was found in the inspected stock
startup path; retaining a package in user storage does not create one.
See [sources, bench evidence and alternatives](../development/rfid-bespok-boot-anchor-2026-11-17.md).

The user selected further development of the minimal `.debug` approach.
A [bench loader and rollback prototype](../development/rfid-debug-loader-2026-11-17.md)
now exists. This does not authorize physical installation: `.debug` retains the
entire overlay; real overlay backup and hardware service control remain unverified.
The laboratory wrapper is not a deployable U1 package.

Manual assignments need no module. RFID requires a compatible Python extra,
`tracker_uid.cfg` and a Klipper include. A config line alone is insufficient.
No firmware image is flashed: the observer wraps approved reader methods in memory
while preserving the original callback arguments and result.

## Compatibility

Only these exact raw `fm175xx_reader.py` SHA-256 snapshots are supported:

| Driver snapshot | SHA-256 |
| --- | --- |
| 1.3.0.168 | `c118a0ff0077d789a558f738bead5cf8e10e28a0a57bb693ba47212303c6ece6` |
| 2.0.0.205 | `68ec97fd4dab74a1fb3690f6f2c4e889abac1c2dc9eedaebb43dab2657ddd392` |
| 2.1.0.157 | `ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8` |

These identify a pinned test corpus, not the user's actual firmware. Unknown or
modified sources are rejected without a force option. The module also checks loaded
method code and existing wrappers at startup. Adding a hash alone is not validation.

## Rehearsal

The kit includes the Python 3.9+ POSIX tool (standard library only), module, RU/EN
instructions and a manifest with file hashes and source commit. Verify the archive
SHA-256 against the supplied report. The manifest detects corruption; it is not a
signature or proof of origin.

Use an independently prepared temporary simulator with `klipper/klippy/extras/`,
`printer_data/config/printer.cfg` and the simulator marker. Do not use sudo.
Stop the simulated Klipper first: `.klipper-running` prevents writes. Its absence
is only a bench convention, not proof that a real service has stopped.

From the extracted kit, for that **prepared simulator only**:

```sh
python3 rfid_module_tool.py inspect --simulator-root /private/tmp/rfid-test/a
python3 rfid_module_tool.py plan --simulator-root /private/tmp/rfid-test/a > /private/tmp/rfid-plan.json
python3 rfid_module_tool.py install --simulator-root /private/tmp/rfid-test/a --plan /private/tmp/rfid-plan.json
python3 rfid_module_tool.py inspect --simulator-root /private/tmp/rfid-test/a
```

Inspect/plan are read-only. Review exactly three changes: a new extra, its config,
and the include appended to printer.cfg. The plan binds the root, driver, module,
config tree and original contents. Changes invalidate the plan. Upgrades require
rollback and a newly reviewed plan; repeat installation is idempotent.

Before writes, a distinct immutable backup is stored under
`.tracker-uid-backups/<id>.json` (0600), followed by a transaction journal. Every
installation retains its own backup. Old unsupported journal schemas require
manual inspection, not deletion or automatic conversion. Included configs are
checked for cycles, missing files, existing tracker_uid sections and wildcard
includes that would load the new config twice. Symlinks and hardlinks are refused.

The harness then starts Klipper and verifies the Moonraker tracker_uid object:
schema 1, ready state, expected driver version, fresh epoch and four channels.
Verify an observed test tag on its actual channel and the stock callback.
File inspection alone is not a runtime or physical RF check.

## Rollback

Stop simulated Klipper, then run:

```sh
python3 rfid_module_tool.py rollback --simulator-root /private/tmp/rfid-test/a
```

Only owned files and the exact include block are removed. Unrelated later main
config edits are preserved. The stock driver is never restored or changed, even
if it was independently upgraded. Start Klipper again to clear in-memory hooks;
there is no live unloading. Confirm ordinary printer telemetry, absence of the
tracker_uid object and manual Tracker operation.

After interrupted installation, roll back. After interrupted rollback, repeat
rollback: its saved restoration plan makes the operation resumable. All files are
validated before writes. Corrupt backups/journals, foreign module edits or concurrent
changes stop the operation rather than overwriting data. Preserve the directory
for investigation; do not erase journals or blindly overwrite current configs.
Changes before our include was written may require manual conflict resolution.

Backups remain after rollback; the final journal is retained as
`.tracker-uid-last-rollback.json`. Real-printer deployment needs separate approval,
actual driver/path validation, verified service stop/start, an independent recovery
path and an idle printer. Physical antennas/tags and firmware upgrades on the real
U1 remain untested. This POSIX installer does not validate the Windows GUI.
