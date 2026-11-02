<img width="1672" height="941" alt="Изображение ChatGPT 29 сент  2026 г , 17_15_54-1" src="https://github.com/user-attachments/assets/0381af22-11cb-4714-8355-3721fa33dbac" />

# Snapmaker U1 Spool Tracker

> **1.1 public beta in preparation:** see the [beta release notes](RELEASE_NOTES_1.1.0-beta.1.md), [English beta quick start](MANUAL_1.1_BETA_EN.md), and [Russian beta guide](MANUAL_1.1_RU_DRAFT.md). The beta uses a separate inventory, is experimental, and is not yet a published release. The installation instructions below describe **v1.0.1**.

A small, local-first preflight utility for Snapmaker U1 and Snapmaker Orca / OrcaSlicer. It compares the per-tool filament requirement in G-code with four physical spool assignments: Slot 1 → T0 through Slot 4 → T3.

## What it does

- Keeps a local inventory of physical spools and remaining grams.
- Checks `; filament used [g] = ...` before G-code export. This preliminary check assumes a direct tool-to-slot mapping; the actual U1 mapping is verified only at print start. A provisional shortage opens a native Cancel Export / Proceed Anyway dialog.
- Cancelling returns a nonzero exit code. Proceed Anyway and a successful check return zero. The G-code is not modified.
- A missing or invalid per-tool usage line is an error and cancels export. The latest result, with one row per toolhead, is shown on the dashboard.
- Export creates a planned job but never deducts filament. In the unreleased working tree, the optional local U1 monitor can also record a newly observed print directly from its verified G-code, including jobs started in Orca or on the printer. A successfully completed, continuously monitored job deducts its estimated T0–T3 usage once only when the physical tool mapping and spool assignments are verifiable. Re-exporting or uploading a file cannot consume inventory. Cancelled/error jobs do not deduct the full estimate. If U1 automatic filament replenishment is enabled or unknown, or monitoring or mapping evidence is incomplete, the job requires review and no automatic deduction is made. This direct-job accounting is not in the existing beta2 build.
- A configurable reserve in grams is added to each **used** toolhead's requirement for the check only. The default is 0 g.

Material mismatch checking is deferred until a reliable per-tool material field is confirmed in Snapmaker Orca output. The tracker never guesses material from a spool name.

**Unreleased 1.1 beta:** The validated alpha observed print starts from both Orca Print and the stock U1 screen on one physical U1; see [the evidence](dev/PRINT_START_ALPHA_TEST.md). The beta adds Off, Warn only (default), and experimental Strict modes. It compares the active remote G-code with assigned T0–T3 spools even without an Orca export plan. Warn only shows a warning and never controls the printer. Strict can issue a pause if the file is risky or unverifiable; only the exact Tracker-paused job may be resumed or cancelled from the dashboard. Strict polls every two seconds, then downloads and checks the file, so a pause can occur **after extrusion has begun**. A single beta2 pause and resume was confirmed on a physical U1; other cases remain to be validated. Follow [the beta test checklist](dev/PRINT_START_GUARD_BETA_TEST.md).

**Physical beta1 finding:** the U1 began processing the pause roughly 15 seconds after receiving it; beta1 had already timed out after 5 seconds and could not verify the result. Do not repeat strict-mode tests with beta1. The unreleased beta2 waits in a separate thread, allows up to 60 seconds for a control response, does not retry an ambiguous command, and switches to Warn only when its result remains unknown. This change is simulator-tested only; switching modes cannot retract a command already sent, and a delayed command may still execute after the client loses its response. Do not start another job until the U1 outcome is resolved.

**Tool mapping in beta2:** the start check reads `print_task_config.extruder_map_table` from the active U1 job, verifies that it and the job identity remain unchanged while reading G-code, and sums logical-tool usage per physical T0–T3. An absent, invalid or changing mapping is **unverified**, not OK. The beta supports at most four logical usage entries. For a matching export plan, automatic debit requires an observed active job, a stable mapping and spool assignments, automatic replenishment confirmed off, and uninterrupted monitoring; otherwise the run is marked for manual review. Accounting remains estimate-based and beta2 jobs without export plans are not automatically debited. Remapped physical prints have not yet been validated on U1 hardware.

**Isolated Mac beta:** `1.1.0-beta2` makes its own data copy on first launch from the existing Tracker inventory and printer settings, starts in Warn only mode, and clears copied job history. It never synchronizes its test changes back to the regular Tracker. Quit the existing Tracker via the menu bar before opening the beta; the beta uses the same local port. See [beta test instructions](dev/PRINT_START_GUARD_BETA_TEST.md).

## Install and use

Download v1.0.1 from [GitHub Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.0.1). On macOS, unpack `SnapmakerSpoolTracker-macOS.zip`, move `SnapmakerSpoolTracker.app` to `/Applications`, and open it; the unsigned app may require **Open** from the context menu. On Windows, put `SnapmakerSpoolTracker-Windows.exe` in a stable folder such as `C:\Tools\SnapmakerSpoolTracker` and run it to show the tray icon. The native Windows dashboard requires Microsoft Edge WebView2 Runtime.

Click the menu-bar/tray icon and choose **Configure Spools & Slots**. The native pywebview window updates print state, preflight results, and balances live. Closing it leaves the tray app running; reopen it from the menu. A second launch does not create another tray instance, but the tray command is the reliable way to reopen a window closed with X. Add real spools, set their initial weights, and assign the four slots. A fresh installation starts empty. The local `http://127.0.0.1:8765` page is for troubleshooting only.

For automatic accounting, enter the U1 hostname/IP (default `U1.local`) and Moonraker port (`7125`) under **U1 printer monitor**, use **Test Connection**, enable the monitor, and save. Keep the tray app running. Preflight works offline. Beta2 matches filename, SHA-256, byte size, printer, and preflight time and captures the verified physical mapping and spool assignments during the active print. Persistent run identity prevents double debit. A monitoring gap, unavailable mapping, automatic replenishment or changed spool assignment requires manual review rather than automatic debit. Weigh and correct a spool when real use differs from the slicer estimate. A job without a matching export plan is checked but not automatically debited.

In Snapmaker Orca / OrcaSlicer, add the executable to **Print Settings → Others → Post-processing scripts**. Include the trailing semicolon required by the slicer:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker-Windows.exe;
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

No cloud, account, telemetry, firmware modification, or network listener beyond `127.0.0.1` is used. The released v1.0.1 monitor and the beta's default Warn only mode read the printer's stock local Moonraker API. The beta's optional Strict mode may send pause, resume, or cancel commands for a matching print.
