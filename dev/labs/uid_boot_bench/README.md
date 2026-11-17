# U1 cold-boot policy laboratory

This experiment follows read-only inspection of one U1 2.1.0.157. **It is not an
installer for a physical printer.** There is no SSH, network discovery, mounting,
firmware flashing, or service/MCU control. Never copy these fixtures to a printer.

`model.py` models the observed policy with ordinary files in a new marked root:

- `klipper/`: materialized system subtree, restored from `_boot_lower/klipper/`
  when the simulated `persistent/.debug` is absent;
- `system/`: other modeled system files (for example service/config files),
  restored from `_boot_lower/system/` under the same policy;
- `printer_data/`: persistent configuration/data, representing `/oem/printer_data`;
- `persistent/`: markers and durable deployment records outside the discarded tree;
- config is restored from origin if `.printer_data` is absent, or when neither
  `.fluidd` nor `.factory` is present; existing extra cfg files are not blanket-deleted.

This is not a kernel OverlayFS test. It does not emulate the complete root filesystem,
physical fsync/power-loss semantics, MCU behavior, watchdog/lmd, or an actual firmware
updater. Recorded source excerpts are evidence; the vendor scripts are never executed.

Two compared paths:

1. Existing three-file installation with no persistence: initially works, then
   loses the extra while keeping its config. Real Klipper reports invalid section.
2. **Explicitly acknowledged whole-overlay persistence**, modeled by `.debug`.
   A durable plan precedes the marker, the module precedes activation, and rollback
   disables the include first. Installer metadata is in the modeled OEM area.
   Pending installation must be rolled back before retry. Existing persistence is
   retained. Foreign changes within both modeled system trees prevent
   automatically disabling a persistence marker created by the trial.

The second path is a candidate, not a recommendation to set `.debug` on U1. That
marker affects the entire system overlay. The model now inventories files, directories,
modes, ownership and symlink targets outside Klipper too; symlinks are never followed.
Additions, modifications and missing entries are compared. Special files/hardlinks
are rejected. Python cache entries in Klipper are excluded. Pre-existing volatile
changes block installation, since retaining them would change their next-boot behavior.
A real implementation still needs inventory and recovery of the entire actual overlay:
this materialized fixture does not model real whiteouts, opaque directories, ACLs,
xattrs, mount boundaries, concurrent system writers or all system services.
It must also address external firmware updates. Removing only `.debug` remains an
unsafe state while the module is configured; the experiment intentionally exposes it.

The observed vendor updater removes `.printer_data` before `.debug`. Tests cover
that first boundary and both removals. A test removing only `.debug` is an independent
marker-loss scenario, **not a claim about the observed updater's operation order**.
The controlled update scenario rolls back UID integration before either removal;
the bench cannot enforce that procedure for a user's future OTA update.
Changes to the modeled firmware lower tree/config block old-backup rollback before
any writes. They do not trigger reinstallation. Foreign system changes also block
update preparation because the vendor cleanup could erase them. The diagnostic
shows exact changed entries. Resolving those changes is deliberately not automated.

Independent recovery kit (Python 3 standard library; POSIX simulators only):

```sh
python -m dev.labs.uid_boot_bench.export_recovery --output output/rfid-recovery-kit
python3 -I output/rfid-recovery-kit/recover.py inspect --simulator-root /absolute/bench
python3 -I output/rfid-recovery-kit/recover.py rollback --simulator-root /absolute/bench
```

Use a new output directory. Keep the simulator's `persistent/tracker-deployment/`
and `_boot_lower/` intact; the kit reads its recovery records there, not in the GUI
database. It has no install, SSH, restart or real-printer mode. Checksums validate
packaged code before importing it. They detect corruption, not malicious replacement
of both code and manifest. The kit does not back up or overwrite foreign system files.
An interrupted trial from the older schema 1 is refused for manual review, not migrated.

Run filesystem cases (synthetic driver; no network):

```sh
python -m pytest tests/test_rfid_boot_model.py tests/test_rfid_installation.py -q
```

Run two real localhost Klipper/Moonraker pairs (RF, SPI and MCU simulated):

```sh
python dev/labs/uid_boot_bench/run.py --output output/rfid-boot-process
```

Requires the existing `/private/tmp/tracker-uid-live` runtime and the pinned
`output/uid-bridge-bench/sources/base/tests_support/snapmaker_source/2.1.0.157`
driver corpus. Hash is asserted. Ports are 18811/18812; all data is generated in
`/private/tmp/rfid-boot-process-*`. No Tracker GUI or user database is opened.
The runner stops only its own processes in `finally`, saves errors/logs/results,
and attempts rollback. Failed cleanup is reported, never hidden as success.

Unit tests inject interruption at every modeled installation and rollback boundary.
Process checks include the naive failure, recovery, fresh UID epoch, stock callback,
interrupted include commit/rollback, unknown driver, and pre-update removal. They
are not measurements of physical tag-reading or tests of the packaged desktop app.
