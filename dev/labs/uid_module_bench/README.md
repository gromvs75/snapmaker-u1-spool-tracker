# Tracker UID Klipper module bench

From repository root, Python 3.11 + pytest:

```
python -m pytest dev/labs/uid_module_bench dev/labs/uid_bridge_bench -q
```

Uses pinned source snapshots prepared by the preceding UID bench; see its README.
All installation targets are temporary marked filesystem fixtures, never a printer.
`install.py` deliberately rejects roots without the simulator marker and has no SSH
or service-control capabilities. Do not use it to deploy to a real printer.

The deployable extra is `dev/klipper/tracker_uid.py`. Module loading, event handlers,
queueing and webhook invocation are exercised with fake Klipper surroundings. The
real pinned reader code runs against mocked low-level radio responses. This is not
a full live Klipper/Moonraker process, RF test or authorization for deployment.

See [results, API and limits](../../../docs/development/uid-klipper-module-bench-2026-11-10.md).
