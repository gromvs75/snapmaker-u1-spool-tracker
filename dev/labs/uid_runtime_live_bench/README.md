# Queued collectors on two real process benches

Requires the prepared `/private/tmp/tracker-uid-live` environment from
`dev/labs/uid_live_bench/README.md`. Run from the repository root:

```sh
PYTHONPATH=/private/tmp/tracker-cancel-test-env/lib/python3.9/site-packages \
/private/tmp/tracker-uid-live/env/bin/python dev/labs/uid_runtime_live_bench/run.py
```

PYTHONPATH only supplies the existing local test dependencies; omit it in an
environment already containing all Tracker dependencies. Local server/socket
permission is required. Endpoints are fixed to `127.0.0.1:18741` and `:18742`.
Each run creates a fresh marked `/private/tmp/uid-runtime-live-*` directory.
No installed Tracker paths or real printer addresses are read.

The runner uses real Klipper/Moonraker processes, UID WebSockets, the corrected
MotionStreamRecorder over `/klippysocket`, two HTTP history readers and one
AccountingOwner SQLite thread. `bench_motion.py` supplies synthetic per-head
trapq-shaped messages and simulated feed/tag status inside Klipper; it changes
print_stats via its normal methods. Moonraker creates its own history IDs and
terminal records. This is NOT actual extrusion, real hardware trapq capture,
physical RFID validation, or a check of mass accuracy. Slicer parameters are an
explicit fixture (PLA, 1.75 mm, 1.24 g/cm³), attached to the history identity.

The scenario covers overlapping jobs, cancellation/completion, history replay,
Moonraker stop/restart during a second job, the unaffected printer completing,
re-subscription, and history replay after reopening the SQLite owner. A graceful
Moonraker shutdown records `server_exit` rather than cancellation for its active
job; that interrupted capture remains blocked. Cleanup stops workers and all
four processes, removes the test config section, rolls back UID modules, and
checks original configs. Results, logs and a test DB copy go only to
`output/uid-runtime-live-bench/` (do not commit generated artifacts).
