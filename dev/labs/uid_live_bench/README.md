# UID: real Klipper / Moonraker process bench (macOS)

This is a disposable localhost integration fixture, **not a printer installer**.
Never copy `bench_radio.py` to a printer. No real SPI, GPIO, serial, CAN or printer
IP is used. Root is deliberately fixed to `/private/tmp/tracker-uid-live`.

## Reproduce the prepared bench

From the repository root:

```sh
/private/tmp/tracker-uid-live/env/bin/python dev/labs/uid_live_bench/run.py
```

Socket permission is required. The runner binds HTTP to `127.0.0.1:18726`, rejects
an occupied port, validates the simulator marker, uses separate config/database,
and stops its child processes in `finally`. It tests baseline, installation,
HTTP/WebSocket, real RESTART, unsupported driver, rollback and stock behavior.
The final state is **module uninstalled, processes stopped**. Results are written
to `output/uid-live-bench/results.json`; `completed` must be true.

## Preparation from scratch

Use local clones of these official repositories at these exact revisions:

- `https://github.com/Klipper3d/klipper.git` → `ROOT/klipper`,
  `56a9c605e121c6560f5c8b6c0e33bdda86de69a1`.
- `https://github.com/Arksine/moonraker.git` → `ROOT/moonraker`,
  `b559b9a81161f958a43c2f527b6ad96f73310d5d`.

Create a Python 3.11 virtualenv at `ROOT/env`. Install Moonraker from its local
checkout plus `greenlet cffi pyserial python-can msgspec websocket-client`.
Exact tested packages are recorded in `output/uid-live-bench/dependencies.txt`.
These are the macOS bench dependencies, not the printer's production environment
or Klipper's exact pinned requirements (notably Jinja2 3.1.6 is used here).

Moonraker's libnacl needs a full libsodium library. The PyNaCl wheel's library
lacks required symbols and is insufficient. The test used official
`https://download.libsodium.org/libsodium/releases/libsodium-1.0.20.tar.gz`,
unpacked under ROOT, configured with a prefix under ROOT, and compiled with
`make -j4`. On Darwin 27 its old libtool failed at final linkage; linking the
already compiled `src/libsodium/**/.libs/*.o` once each with `clang -dynamiclib`
produced `ROOT/env/lib/libsodium.dylib`. No system library was installed.

Run `env/bin/python dev/labs/uid_live_bench/prepare.py` once after dependencies.
It refuses an existing bench config. It compiles upstream Klipper C helpers using
Clang and two local compatibility headers (`prctl` thread naming, CAN structure).
CAN is not used. No tracked Klipper/Moonraker core source is modified.
It copies the pinned original Snapmaker 2.1.0.157 driver from the preceding bench
corpus and adds a clearly separate hardware fixture.

## What is real and what is simulated

Real: Klippy process, config loader/includes, reactor, driver constructor and
background scan thread, original UID activation/cascade method, module load,
Unix socket, Moonraker process/database/HTTP/WebSocket, restart and file rollback.

Simulated: SPI/GPIO/RF replies, material authentication failure, MCU dictionary
and output (`-o`, upstream Klipper debug-file mode), `kinematics: none`.
No physical RF reliability, actual U1 OS/service installation or motion tested.
The synthetic MCU dictionary is only sufficient for this no-motion fixture.

Moonraker uses its built-in `provider: none`, `file_system_observer: none` and
local announcements mode. Expected macOS diagnostics include missing D-Bus,
`ip`, `/proc`, and `SO_PEERCRED`; they are not suppressed or patched. HTTP and
WebSocket checks pass, but this does not validate Linux service management.

See [report](../../../docs/development/uid-live-klipper-moonraker-2026-11-10.md).
