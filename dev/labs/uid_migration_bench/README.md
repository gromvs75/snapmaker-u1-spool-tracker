# Offline legacy migration bench

Only synthetic schema-5 files inside a directory marked
`.tracker-migration-bench` with contents `synthetic-only` are accepted. No user
path discovery, networking or installed Tracker updates exist in this runner.

```sh
python dev/labs/uid_migration_bench/run.py
python -m pytest tests/test_uid_migration.py -q
```

Use an environment with pytest, filelock and the existing Tracker dependencies.
The environment used here was `/private/tmp/tracker-uid-live/env/bin/python`
with `/private/tmp/tracker-cancel-test-env/lib/python3.9/site-packages` added to
PYTHONPATH for local dependencies. Generated proof files remain in
`output/uid-migration-bench/` and must not be committed.

`legacy_storage_fixture.py` and `spoolman_bridge.py` are pinned copies from
`output/cancel-accounting-fix-2026-11-10/src/`. They are supplied to the migrator
as the explicit validator; the older root storage module is NOT the schema-5
validator. No Bridge instance or remote client is started. The pinned Store is
also used to prove that a legacy writer rejects the cutover fence.

`BenchMigration(root, validator=validate_db).migrate(printer_ids, uid_bindings)`
requires explicit old `host:port` → persistent printer ID mapping and explicit
spool ID → UID mapping. Missing UIDs remain archived/manual-only. Local tagged
spools retain their IDs and current balances. Every historical run is fenced;
history is never replayed to calculate the opening inventory. Original source,
plans, spools, run payloads and outbox payloads are retained.

Restore is deliberately a **pre-new-accounting rollback**. It checks the backup
hash and target inventory, requires no live SQLite owner/old writer/Spoolman
worker, and refuses after new jobs/debits or unresolved remote sends. Original
JSON bytes are restored; the migrated target remains disabled. A corrupt target
or post-cutover consumption needs reconciliation, not blind old-balance restore.
The same restored directory remains an audit artifact; use a fresh marked bench
directory for another migration. No automatic retry overwrites artifacts.

Manual-model follow-up: local untagged spools now enter the working catalog with
NULL UID. Imported manual slots require confirmation; ambiguous slots are retained
as candidates. Existing archive-only targets are upgraded without resetting
balances. See `docs/development/uid-manual-spools-2026-11-10.md`.
