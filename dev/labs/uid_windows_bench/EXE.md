# Isolated Windows EXE for GUI 2.0

Build on Windows from the repository with the dependencies pinned in
`.github/workflows/uid-windows-exe.yml`:

```powershell
python -m PyInstaller --clean --noconfirm packaging/TrackerUidGuiWindows.spec
```

Output: `dist/Tracker-2.0-Windows-Bench.exe` (one file, windowed). Ordinary launch
opens the GUI with two simulated printers and a new synthetic SQLite database in
OS TEMP. It never reads installed Tracker configuration or user inventory. This
is the isolated 2.0 bench, not a replacement installer for the stable application.
The runtime uses Windows WebView2; the tested runner includes it.

For CI only, on a dedicated disposable Windows desktop:

```powershell
$p = Start-Process ./Tracker-2.0-Windows-Bench.exe -ArgumentList '--ci-self-test --output C:\bench-results' -PassThru -Wait
$p.ExitCode
```

The CI flag sets the screen to 1920×1080, moves the mouse, runs the native GUI
scenarios, writes screenshots/JSON, closes the window, and returns nonzero on
failure. It only works in the frozen EXE. It also runs nonzero accounting through
the bundled queue/lifecycle/history implementation on a separate synthetic DB:
two printers, history replay, owner reopen, interrupted capture resolution, late
terminal/history, and another reopen. No pytest or external source imports are
used for this check. The laboratory clock offset only affects the accounting
module, not Windows time.

Actions copies only the EXE to a fresh directory outside the checkout, removes
PYTHONPATH/PYTHONHOME, and verifies `frozen: true` in the result. A separate host
smoke driver launches the EXE without flags and checks native window shutdown and
its synthetic verification files. The workflow uploads the successful EXE and
SHA256 plus test artifacts. It neither publishes a release nor installs the app.
