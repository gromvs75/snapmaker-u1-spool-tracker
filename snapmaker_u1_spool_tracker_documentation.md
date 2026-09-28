# Technical notes for v1.0.1

The app has a tray process, a localhost dashboard, and a separate Orca post-processing process. Both share `spools_u1.json` in the per-user application data directory. `storage.py` uses a stable lock file, reads current state under the lock, validates schema version 1, writes a temporary file, fsyncs it, and atomically replaces the database. Legacy schema without `schema_version` is migrated on read. A damaged database is preserved and copied into `backups/`; no silent reset occurs.

`gcode.py` reads the file tail first, then streams a fallback if metadata is not near the end. It requires a valid per-tool `; filament used [g] = ...` line. `preflight.py` compares each active tool's requirement plus reserve with its assigned spool. The hook returns zero for OK or explicit Proceed Anyway, nonzero for Cancel, parse failure, or storage error. It never changes G-code or subtracts inventory on export.

The dashboard binds only `127.0.0.1:8765`. JSON POST requests require an appropriate host, same origin when provided, `application/json`, and at most 64 KiB. User input is rendered with DOM text nodes. The tray menu refreshes after database changes. An existing tracker instance opens its dashboard on a second launch.

For user setup, see [README](README.md), [English manual](MANUAL_EN.md), and [Russian manual](MANUAL_RU.md). CI workflows run tests and build Windows `.exe` and unsigned macOS `.app` artifacts. The owner performs real Orca and printer checks before tagging a release.

Material mismatch detection is deferred because the current parser has no verified stable per-tool material metadata. Add it only after capturing representative Snapmaker Orca output and testing the mapping to T0–T3.
