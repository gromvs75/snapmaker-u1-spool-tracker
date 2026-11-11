# Windows EXE + two real Klipper/Moonraker process benches

The `uid-windows-live.yml` Actions workflow creates a disposable Ubuntu 22.04 WSL1
instance on a Windows runner. WSL1 shares loopback with Windows; no external
printer address, tunnel or public service is used.

| Component | Runtime | Data |
| --- | --- | --- |
| Frozen Tracker EXE, GUI, collectors, one SQLite owner | Windows | New TEMP SQLite |
| Klippy A and Moonraker A | Ubuntu WSL1 | Marked temporary A directory |
| Klippy B and Moonraker B | Ubuntu WSL1 | Separate marked temporary B directory |
| Process supervisor | Ubuntu WSL1 | Loopback 18780, per-run token |

Real: four upstream processes, Unix sockets, Moonraker databases/history,
HTTP/WebSocket subscriptions, stop/start of Moonraker A, Windows native WebView2
and mouse input, persistent SQLite accounting. Simulated: MCU debug output,
SPI/GPIO/RFID and motion messages from the clearly marked `bench_motion` extra.
No physical printing or measurement occurs.

Sources:
- Klipper `56a9c605e121c6560f5c8b6c0e33bdda86de69a1` from Klipper3d/klipper.
- Moonraker `b559b9a81161f958a43c2f527b6ad96f73310d5d` from Arksine/moonraker.
- `fm175xx_reader.py`: unchanged pinned Snapmaker 2.1.0.157 corpus fixture from
  the earlier UID bridge bench. Raw SHA256:
  `ce7363f8b512e5474d18bd57cdf0660e6e2df57dc256e22f743b3b28c1b70be8`.
  Its original CRLF bytes must remain unchanged; the local `.gitattributes`
  disables newline conversion. The module installer checks this exact hash.

The EXE's explicit `--ci-live MANIFEST --output DIRECTORY` mode accepts only the
marked fixed loopback topology. Ordinary EXE launch remains synthetic/offline.
The supervisor starts processes, clears test tag channels, records PIDs and
restarts, then stops all processes and rolls back temporary module installation.
The workflow unregisters only its `TrackerBench` WSL instance at the end.

`prepare.sh` is for the disposable CI Linux instance only: it installs build
packages and clones the pinned sources under `/tmp/tracker-live-source`.
Do not run these fixtures on a printer. Existing multi-printer and module-install
bench code is reused; this is not a deployment script.

Artifacts contain live-result JSON, final SQLite, actual server logs, process PID
and cleanup evidence, screenshots, dependency versions, EXE and SHA256.
