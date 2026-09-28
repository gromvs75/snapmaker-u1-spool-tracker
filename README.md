<img width="1200" height="630" alt="Snapmaker U1 Spool Tracker" src="https://github.com/user-attachments/assets/510afc4c-a9d1-4c28-b101-35c3f924309c" />

# Snapmaker U1 Spool Tracker

A small, local-first preflight utility for Snapmaker U1 and Snapmaker Orca / OrcaSlicer. It compares the per-tool filament requirement in G-code with four physical spool assignments: Slot 1 → T0 through Slot 4 → T3.

## What it does

- Keeps a local inventory of physical spools and remaining grams.
- Checks `; filament used [g] = ...` before G-code export. An unassigned spool or insufficient material opens a native Cancel Export / Proceed Anyway dialog.
- Cancelling returns a nonzero exit code. Proceed Anyway and a successful check return zero. The G-code is not modified.
- A missing or invalid per-tool usage line is an error and cancels export. The latest result, with one row per toolhead, is shown on the dashboard.
- Export creates a planned job but never deducts filament. With the optional local U1 monitor enabled, a matching successful printer job automatically deducts its T0–T3 estimate once. Re-exporting or uploading a file cannot consume inventory.
- A configurable reserve in grams is added to each **used** toolhead's requirement for the check only. The default is 0 g.

Material mismatch checking is deferred until a reliable per-tool material field is confirmed in Snapmaker Orca output. The tracker never guesses material from a spool name.

## Install and use

The CI workflows produce an unsigned macOS `.app` and a Windows `.exe` as artifacts. They are not a release until the owner publishes them. On macOS, move the app to `/Applications`; macOS may require **Open** from the context menu on first launch. On Windows, put the exe in a stable folder such as `C:\Tools\SnapmakerSpoolTracker` and run it once to show the tray icon.

Open the tray menu's dashboard or visit `http://127.0.0.1:8765`. Add your real spools, set their weights, and assign the four slots. A fresh installation starts with no spools and no assignments.

For automatic accounting, enter your U1 hostname or IP in **U1 printer monitor** (default `U1.local`), keep Moonraker port `7125` unless you changed it, use **Test Connection**, then enable the monitor and save. Keep the tray app running. Preflight works even if the printer is offline; the monitor resumes from Moonraker history on reconnect or app restart. The planned job must match the printer's filename and G-code SHA-256. A cancelled or errored job is not charged its full estimate. If a printed file was deleted or changed before the monitor could verify it, or multiple plans with different spool assignments match, the tracker leaves inventory unchanged for that job and manual review is needed. Weigh and correct a spool when actual consumption differs from the slicer estimate.

In Snapmaker Orca / OrcaSlicer, add the executable to **Print Settings → Others → Post-processing scripts**. Include the trailing semicolon required by the slicer:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker.exe;
```

If the path contains spaces, quote the executable path. Save the process preset. Check this integration with a small real slice before relying on it.

For source use on macOS, install `requirements.txt`, then run `python spool_tracker.py` for the tray and use `run_hook.sh;` as the post-processing command. The hook expects the G-code path as its first argument.

See [English manual](MANUAL_EN.md) or [Russian manual](MANUAL_RU.md) for a step-by-step setup.

## Data and recovery

- macOS: `~/Library/Application Support/SnapmakerSpoolTracker/spools_u1.json`
- Windows: `%LOCALAPPDATA%\SnapmakerSpoolTracker\spools_u1.json`
- Linux source use: `${XDG_DATA_HOME:-~/.local/share}/SnapmakerSpoolTracker/spools_u1.json`

The same directory contains `tracker.log` (rotated), a lock file, and `backups/` if corruption is detected. On first launch, a valid old `spools_u1.json` beside the previous executable or source script is copied into the new location. The old file stays in place. A corrupt new database is never silently reset: the original stays untouched, a timestamped backup is made, and the app reports an error. Restore a known good copy before continuing. Back up the data directory before removing a previous installation.

## Build and test

Python 3.11 is used in CI. Run `python -m pip install -r requirements-dev.txt` and `python -m pytest -q` locally. GitHub Actions runs tests on Linux and before both Windows and macOS builds. Build artifacts are uploaded; no tag or release is created automatically.

No cloud, account, telemetry, firmware modification, or network listener beyond `127.0.0.1` is used. When enabled, the monitor makes read-only requests to the printer's stock local Moonraker API.
