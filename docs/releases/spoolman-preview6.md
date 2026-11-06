# Spoolman Preview 6 — unpublished test build

Date: 2026-11-06. macOS Apple Silicon. Stock Snapmaker U1 firmware.

## Change

After importing a Tracker backup, the Spoolman settings now reload immediately,
including the read/send switches and sole-sender confirmation. Previously the
backend correctly disabled integration, but the form could retain the pre-import
send settings. No accounting or Spoolman protocol changes were made.

Separate app: SnapmakerSpoolTracker-Spoolman-Preview6.app; bundle ID
local.snapmaker-spool-tracker.spoolman.preview6; local UI port 8776; fresh default
inventory directory ~/Library/Application Support/SnapmakerSpoolTracker-SpoolmanPreview6.
No automatic migration from installed Tracker or earlier previews.

## Documentation and licensing

Expanded Russian integration guide: setup, physical spool IDs, stock firmware,
Snorca forecasts versus registered print plans, read/send modes, failures,
per-spool uncertainty, separate Tracker/Spoolman backups, and troubleshooting.
Updated English guide. Full Spoolman 0.27.1 MIT license and attribution included.
Spoolman server/client is separate and not bundled. Tracker remains MIT-licensed.
Docker setup is documented from upstream; the local test server ran from source.

## Validation

- 81 tests: Spoolman bridge, backup and HTTP U1 simulator; 4 dashboard JavaScript tests.
- Native Preview 6 settings: send mode cannot save without sole-sender checkbox;
  send mode saved through UI; monitor configured only for loopback simulator.
- Packaged app observed simulated print start/completion and sent exactly 20 g
  to new test spool #11 (1000 -> 980 g). UI showed Confirmed.
- Native JSON export before/after print and native JSON import completed.
- A synthetic pending backup fixture was derived from the test-only exported
  confirmed operation. Restore disabled integration and marked it uncertain.
  UI Already applied flow required a note and confirmation. Server balance was
  checked before resolution; no second deduction occurred.
- On rebuilt app, imported the actual before-print backup: mode and all switches
  immediately showed Off (regression fixed). Returned UI to Read only, printer off.
- Simulator-driven scripts separately covered repeated history, component restart,
  read-to-send, off/reconnect, old backup, pending backup and multicolour disconnect.
  These scripts do not constitute UI verification of every failure path.
- Test data isolated by HOME; original user Preview 5 inventory compared byte-for-byte.
  All pre-existing Spoolman spools unchanged. No real printer was contacted.

## Limits

Ad-hoc signed, not notarized. Windows GUI remains unverified; no Windows build was
prepared for this iteration. Sustained physical-print validation remains pending.
Nothing was published. Installed Tracker was not replaced.
