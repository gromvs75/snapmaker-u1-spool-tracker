<img width="1200" height="630" alt="Snapmaker U1 Spool Tracker" src="https://github.com/user-attachments/assets/510afc4c-a9d1-4c28-b101-35c3f924309c" />

# Snapmaker U1 Spool Tracker

A small, local-first preflight utility for Snapmaker U1 and Snapmaker Orca / OrcaSlicer. It compares the per-tool filament requirement in G-code with four physical spool assignments: Slot 1 → T0 through Slot 4 → T3.

## What it does

- Keeps a local inventory of physical spools and remaining grams.
- Checks `; filament used [g] = ...` before G-code export. An unassigned spool or insufficient material opens a native Cancel Export / Proceed Anyway dialog.
- Cancelling returns a nonzero exit code. Proceed Anyway and a successful check return zero. The G-code is not modified.
- A missing or invalid per-tool usage line is an error and cancels export. The latest result, with one row per toolhead, is shown on the dashboard.
- Export creates a planned job but never deducts filament. With the optional local U1 monitor enabled, a matching successful printer job automatically deducts its T0–T3 estimate once. Re-exporting or uploading a file cannot consume inventory. Cancelled/error jobs do not deduct the full plan.
- A configurable reserve in grams is added to each **used** toolhead's requirement for the check only. The default is 0 g.

Material mismatch checking is deferred until a reliable per-tool material field is confirmed in Snapmaker Orca output. The tracker never guesses material from a spool name.

## Install and use

The CI workflows produce an unsigned macOS `.app` and a Windows `.exe` as artifacts. They are not a release until the owner publishes them. On macOS, move the app to `/Applications`; macOS may require **Open** from the context menu on first launch. On Windows, put the exe in a stable folder such as `C:\Tools\SnapmakerSpoolTracker` and run it once to show the tray icon. The native Windows dashboard requires the Microsoft Edge WebView2 Runtime.

Click the menu-bar/tray icon and choose **Configure Spools & Slots**. The native pywebview window updates print state, preflight results, and balances live. Closing it leaves the tray app running; reopen it from the menu. A second launch does not create another tray instance, but the tray command is the reliable way to reopen a window closed with X. Add real spools, set their initial weights, and assign the four slots. A fresh installation starts empty. The local `http://127.0.0.1:8765` page is for troubleshooting only.

For automatic accounting, enter the U1 hostname/IP (default `U1.local`) and Moonraker port (`7125`) under **U1 printer monitor**, use **Test Connection**, enable the monitor, and save. Keep the tray app running. Preflight works offline; the monitor recovers from Moonraker history after reconnect/restart. It matches filename, SHA-256, byte size, printer, and preflight time, and debits the spool IDs captured at preflight. Persistent run identity prevents double debit. Deleted/changed remote files or ambiguous plans leave inventory untouched for review. Weigh and correct a spool when real use differs from the slicer estimate.

In Snapmaker Orca / OrcaSlicer, add the executable to **Print Settings → Others → Post-processing scripts**. Include the trailing semicolon required by the slicer:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker.exe;
```

If the path contains spaces, quote the executable path. Save the process preset. Check this integration with a small real slice before relying on it.

For source use on macOS, install `requirements.txt`, then run `python spool_tracker.py` for the tray and use `run_hook.sh;` as the post-processing command. The hook expects the G-code path as its first argument.

See the [English manual](MANUAL_EN.md) or [Russian manual](MANUAL_RU.md) for setup, job states, backup, restore, and safe upgrades.

## Data and recovery

- macOS: `~/Library/Application Support/SnapmakerSpoolTracker/spools_u1.json`
- Windows: `%LOCALAPPDATA%\SnapmakerSpoolTracker\spools_u1.json`
- Linux source use: `${XDG_DATA_HOME:-~/.local/share}/SnapmakerSpoolTracker/spools_u1.json`

Use **Backup & Restore → Export Backup** in the native window to save a portable JSON file outside this directory; **Import Backup** validates it, saves a local pre-import copy, and atomically replaces inventory, settings, and accounting history without restart. The exported file excludes transient printer connection state. The data directory also contains `tracker.log`, a lock file, and internal `backups/`. A valid old database beside a previous executable/script can migrate on first launch. Corrupt data is preserved and reported, never silently reset.

For a macOS update, Quit, export a portable backup, unpack the new `.app`, drag it to `/Applications`, and choose **Replace**. Do not uninstall with AppCleaner/CleanMyMac first if retaining data: they may remove the entire Application Support directory, including internal backups. A portable file saved elsewhere survives. Export before a Windows uninstall or move too. For complete removal, delete the data directory only when you intend to erase inventory/history.

## Build and test

Python 3.11 is used in CI. Run `python -m pip install -r requirements-dev.txt` and `python -m pytest -q` locally. GitHub Actions runs tests on Linux and before both Windows and macOS builds. Build artifacts are uploaded; no tag or release is created automatically.

For testing automatic accounting without a physical printer, see the [local U1/Moonraker simulator](dev/README_MOCK_U1.md). It is a development tool and is not included in the packaged app.

No cloud, account, telemetry, firmware modification, or network listener beyond `127.0.0.1` is used. When enabled, the monitor makes read-only requests to the printer's stock local Moonraker API.
