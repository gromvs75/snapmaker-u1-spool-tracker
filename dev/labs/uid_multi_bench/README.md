# Multi-printer UID client bench

Requires the prepared macOS environment from `../uid_live_bench/README.md`.
Run from repository root, with localhost socket permission:

```sh
/private/tmp/tracker-uid-live/env/bin/python dev/labs/uid_multi_bench/run.py
/private/tmp/tracker-uid-live/env/bin/python -m pytest tests/test_uid_client.py dev/labs/uid_module_bench dev/labs/uid_bridge_bench -q
```

Creates two disposable marked roots `/private/tmp/uid-multi/a` and `b`, copies the
pinned Klipper from the previous bench, installs only the experimental UID extra,
and starts independent Klipper/Moonraker processes on 127.0.0.1:18731 and :18732.
The client starts before the servers to exercise retry. No printer IP, installed
Tracker, or user inventory is read or written. The fixture catalog is separate at
`/private/tmp/uid-multi/catalog.sqlite` and is reset on each bench run.

Real: Klipper/Moonraker processes, Unix sockets, WebSocket subscriptions/queries,
client worker threads, reconnects, Klipper RESTART, SQLite persistence.
Simulated: radio replies, SPI/GPIO, MCU, spool presence and movement.

The bench uses an explicitly test-only `bench_radio/set_tag` endpoint to change
fixture UID/channel. The client itself only calls `printer.objects.subscribe` and
`printer.objects.query`; it never triggers scans, edits firmware or sends G-code.

19 integration checks: startup retry, two independent printers, simultaneous UID
reads, transfer A:T0→B:T2, duplicate protection, offline previous holder, independent
operation of the other printer, Moonraker reconnect, Klipper epoch change, client
restart and persistent catalog, return B:T2→A:T1, missing/reinstalled module, and
WebSocket notifications on both printers. In `finally` clients/processes stop,
module installations roll back, and original fixture configs are checked.

Results: `output/uid-multi-bench/results.json` (`completed: true` required), console
results and per-printer Klipper/Moonraker logs. Radio and macOS compatibility
limitations are the same as the single-printer bench; no Linux/U1 deployment or
Windows GUI validation is implied.
