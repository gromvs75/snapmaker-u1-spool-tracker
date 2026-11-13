# UID + transactional accounting integration bench

Requires the prepared environment documented in `../uid_live_bench/README.md`.
From the repository root, with permission to bind localhost sockets:

```sh
/private/tmp/tracker-uid-live/env/bin/python dev/labs/uid_accounting_bench/run.py
/private/tmp/tracker-uid-live/env/bin/python -m pytest tests/test_uid_accounting.py tests/test_uid_client.py dev/labs/uid_module_bench dev/labs/uid_bridge_bench -q
```

Reuses the two disposable marked printer roots from `uid_multi_bench`, ports
18731/18732. Creates a separate `/private/tmp/uid-multi/accounting.sqlite` and
resets that **fixture database only** on every run. It never discovers or opens
the installed Tracker database. Both process pairs stop and UID modules roll back
in `finally`.

Real: Klipper/Moonraker/UID transport, two client connections, persistent SQLite
catalog, frozen job bindings, atomic inventory/ledger writes, duplicate checks.
Simulated: RF/SPI/GPIO/MCU, and normalized per-tool cumulative print usage events.
`bench_radio/print_event` is a fixture endpoint, NOT a real printer telemetry API.
The test uses overlapping synthetic job lifetimes; it does not execute extrusion
G-code or validate a real physical consumption estimator.

Fourteen integration checks include overlap with identical remote history IDs,
progress, partial cancel, transfer, late replay, DB reopen, source snapshot
import retry, and mid-job spool replacement. Unit tests additionally cover
transaction rollback using an aborting SQLite trigger and concurrent duplicate
receipts on two SQLite connections.

Results: `output/uid-accounting-bench/results.json`, `run-results.txt`, `tests.txt`,
per-printer logs. `completed: true` is required. See
[report](../../../docs/development/uid-accounting-integration-2026-11-10.md).
