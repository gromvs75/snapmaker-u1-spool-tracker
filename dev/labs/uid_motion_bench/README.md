# UID motion adapter: offline bench

Run from the repository root in an environment with pytest and filelock:

```sh
python -m pytest tests/test_uid_motion_adapter.py -q
```

`recorder_fixture.py` is based on the corrected collector
from `output/cancel-accounting-fix-2026-11-10/src/motion_stream.py` (10 November).
It preserves error→cancel handling absent in the older root copy.
It now has optional lifecycle callbacks for observed start, terminal evidence and
socket exit; with a lifecycle supplied, both legacy debit paths are bypassed. It is a test
fixture, not a second production collector. Do not run its network worker.
Tests invoke `_capture` with a fake socket; no socket, printer or installed app
is accessed. Legacy debit functions are replaced by test-only sinks. The real
read-only allocation and motion summarization modules are unchanged and match
the corrected build. The fixture makes replay independent of generated output.

The instrumented collector calls MotionLifecycle.start at the observed transition,
before the history ID is known. MotionLifecycle.history accepts polling batches
and joins a unique filename/time candidate to that saved binding. The simulator
supplies history responses and socket messages, not pre-bound history IDs.
Late history alone is intentionally insufficient. All callbacks run on the same
controlling thread in this offline bench; production threading/network wiring
is not enabled. Socket exit invalidates active bindings. Per-head terminal lengths
come from the collector, not progress or aggregate filament allocation.

Tests cover simultaneous printer identities, cancellation, spool transfer,
reopened SQLite/history replay, UID session change, motion observation gap,
missing/mismatched evidence and actual collector cancellation from printing,
paused and error states including late extrusion and cancellation retraction.

Lifecycle tests: `python -m pytest tests/test_uid_motion_lifecycle.py tests/test_uid_motion_adapter.py -q`.

Threaded multi-printer integration: `python -m pytest tests/test_uid_runtime.py -q`.
This runs two actual recorder instances with simulated sockets and history
readers through `AccountingOwner`; SQLite is opened only in its owner thread.
See `docs/development/uid-runtime-queue-2026-11-10.md` for shutdown and retry rules.
