# Tracker 2.0 Windows GUI CI bench

Run on Windows with Python 3.11 and installed WebView2:

```powershell
python -m pip install pywebview==6.2.1 Pillow==11.3.0 pywin32==311 filelock==3.16.1
python dev/labs/uid_windows_bench/run.py
```

The script creates a fresh synthetic SQLite database under OS TEMP and a loopback
HTTP server on a random port. It does not discover user settings, installed apps,
or real printers. The fleet has two simulated printers. Only the accounting
module's laboratory clock advances; the system clock does not change.

The real native WebView2 window receives Win32 mouse clicks and a drag. DOM
assertions verify consent, expiry, reconnect, renewal, assignment and transfer;
Pillow captures the Windows desktop. Results and screenshots are written to
`output/uid-windows-gui/`. Run on an otherwise unused desktop: mouse automation
moves the pointer. The Actions runner is disposable and dedicated to this check.

The dedicated workflow `.github/workflows/uid-windows-gui.yml` also runs accounting,
collector/history, replay and migration tests. A failed assertion fails the job;
artifacts upload even after failure. No packaging, deployment or releases occur.
The workflow has a 15-minute hard limit, individual pytest cases a 45-second limit.

This is a source GUI test on the hosted Windows runner, not an installed EXE test,
not a Windows 10/11 hardware/DPI matrix, and not two live Klipper processes on
Windows. Collector tests use synthetic sockets and history; actual Klipper/
Moonraker process tests are documented separately in the Linux/macOS bench reports.
