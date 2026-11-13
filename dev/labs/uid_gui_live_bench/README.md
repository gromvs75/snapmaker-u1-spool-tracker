# GUI on two process benches

Requires the prepared environment from `../uid_live_bench/README.md` and the
local test dependencies described in `../uid_runtime_live_bench/README.md`.

```sh
PYTHONPATH=/private/tmp/tracker-cancel-test-env/lib/python3.9/site-packages \
/private/tmp/tracker-uid-live/env/bin/python dev/labs/uid_gui_live_bench/run.py
```

Only loopback endpoints: Klipper/Moonraker pairs at ports 18771/18772, GUI at
18749. Every run creates a new marked `/private/tmp/uid-gui-live-*` tree and DB.
No installed Tracker configuration or user database is accessed. Radio, MCU and
motion are fixtures; Klipper, Moonraker history, transports, recorder, GUI bridge
and SQLite owner are real processes/components.

The runner publishes `output/uid-gui-live-bench/phase.json`. At each checkpoint,
execute the corresponding `async page => ...` Playwright script in this folder:
`initial.js`, `idle-reconnected.js`, `printing.js`, `offline.js`,
`reconnected.js`, `reopened.js`. Only after that script succeeds, create
`output/uid-gui-live-bench/<phase>.continue`. These are test-driver barriers,
not user approvals. Each has a 600-second timeout; timeout/failure runs cleanup.
Use a fresh GUI page at each phase (the scripts reload it). Save returned JSON
as test evidence. The runner stops workers, GUI, fleet and all printer processes,
rolls back the UID modules and checks restored configs in finally.

The recorder uses ModelInventoryStore, not the old fixed-ID Store fixture:
manual IDs and material snapshots must match GUI assignments. Replaying an old
history never consults the new physical location. A disconnected in-progress
capture remains reserved for review, even after Moonraker returns; server_exit
alone does not prove the printer has stopped. Idle reconnection permits a new
physical confirmation and transfer; the test covers both cases separately.

Results/logs/SQLite copies/screenshots are generated under
`output/uid-gui-live-bench/`, not committed. Tests use synthetic PLA parameters
(1.75 mm, 1.24 g/cm³) and 100 mm motion events: 298 mg per complete capture.

## Manual interrupted-job resolution

Run with `--resolve` to test the recovery workflow; output goes to
`output/uid-resolution-live-bench/`. The current runner uses printer ports
18771/18772 (GUI remains 18749). In addition to the original phases, run
`resolve-printing.js` and `resolve.js` after `reconnected`; use
`reopened-resolution.js` for `reopened`. Create barriers in the resolution output
folder. For original scripts, redirect screenshot paths to that folder when
running this mode. This workflow verifies live printing rejection, two explicit
acknowledgements, cancellation, stale versions, client-state injection rejection,
idempotent resolution, transfer after reconfirmation, delayed corrected history,
a genuinely new print, and replay after owner restart.

The GUI receives an explicitly injected read-only `status_reader` bound to the
two known localhost printers. It queries print_stats immediately before submitting
the resolution to the owner queue. No printer stop/cancel command is sent by the
GUI. Without a status reader, the endpoint fails closed. Fixtures issue the
simulated cancellation only after the printing-rejection test passes.

## Temporary unlock across process reconnect and expiry

Run `run.py --temporary` (implies `--resolve`). Current printer ports:
18781/18782; GUI:18749. Output: `output/uid-unlock-live-bench/`.
Use the initial, idle-reconnected, printing, offline, reconnected and
resolve-printing scripts as before, redirecting their screenshot output folder.
Then run window-open.js, window-offline.js, window-expired.js, window-renew.js,
and reopened-resolution.js for the final reopened barrier. Signal each successful
phase with `<phase>.continue` in the temporary-unlock output folder.

Only the accounting module's injected clock advances (+901, then +1802 seconds).
System, Klipper, Moonraker, recorder timestamps and monotonic freshness checks
retain normal time. While the window is pending, Moonraker A disconnects, the
window expires, Moonraker reconnects, and the SQLite owner and collectors restart.
The old deadline must persist and the original request must not extend it. A
renewed GUI confirmation then completes assignments, permits transfers and a new
print. Replay of corrected old history and reopening SQLite must not add debits.
