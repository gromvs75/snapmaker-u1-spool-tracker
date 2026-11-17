# RFID installation kit validation (no hardware)

The source module and deployment tool are tested separately from the exported kit.
All writable roots are new temporary marked simulators. No installed Tracker,
user database, physical printer, SSH, or service manager is used.

```
python -m pytest tests/test_rfid_installation.py -q
python -m pytest dev/labs/uid_module_bench dev/labs/uid_bridge_bench -q
python dev/labs/uid_installation_bench/compatibility.py \
  --corpus output/uid-bridge-bench/sources/base/tests_support/snapmaker_source \
  --output output/rfid-compatibility.json
python scripts/package_rfid_module.py --output output/rfid-module-0.2.0-bench.zip
python dev/labs/uid_installation_bench/run.py \
  --kit output/rfid-module-0.2.0-bench.zip --output output/rfid-kit-process
```

The file tests use tiny synthetic drivers and do not require external fixtures.
The module/bridge and compatibility runs require the pinned source corpus described
in `../uid_bridge_bench/README.md`. Process runs require `/private/tmp/tracker-uid-live`
prepared as described in `../uid_multi_bench/README.md`, plus free loopback ports
18801/18802. RF/SPI/MCU are simulated; Klipper and Moonraker are real processes.

The kit builder refuses to overwrite an existing archive. Use a new output name for
another build. The process runner executes the tool extracted from that archive,
not a source-import substitute. It verifies stock/manual mode, live-process write
rejection, repeated installation, UID read, rollback, fresh epoch on reinstall and
independence of the two printers. Cleanup stops only owned processes, removes the
module and checks exact original config preservation. Logs/results remain in output.

This does not establish physical RF compatibility or authorization for deployment.
The simulator marker/stop-file contract must not be used to bypass real-service
stop verification. The current kit deliberately has no real-printer write mode.
