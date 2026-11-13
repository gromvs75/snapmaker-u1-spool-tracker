# UID bridge bench (no hardware)

Run with Python 3.11 and pytest, from the repository root:

```
python -m pytest dev/labs/uid_bridge_bench/test_uid_pipeline.py -q
```

Requires the pinned source snapshots in `output/uid-bridge-bench/sources/{base,rfid}`.
The commits are recorded in `output/uid-bridge-bench/source-commits.json` and the
[research report](../../../docs/development/uid-bridge-bench-2026-11-10.md).
To reproduce elsewhere, clone `Bespok3d/u1-base` and `Bespok3d/u1-enhanced-rfid`
into those two directories and check out the recorded commits. Do not run their
installers. Dependencies for this harness: Python 3.11, pytest, patch with -F0.

Only temporary source copies are patched. GPIO/SPI imports and low-level radio
results are simulated. No driver constructor is called. There are no printer
connections, persistent production state changes or inventory debits.

`bridge.py` is an event adapter, NOT an installable Klipper module. The tests
compose the callback explicitly; live lifecycle/threads/API/rollback are future
work. A passing test is software evidence, not RF or tag compatibility evidence.

## Memory observer comparison

`memory_bridge.py` and `test_memory_bridge.py` exercise the unmodified driver.
Run the whole directory to compare both paths (159 cases). See
[comparison and limits](../../../docs/development/uid-memory-wrapper-comparison-2026-11-10.md).
Neither adapter is an installable Klipper extra. No real-printer tests were run.
