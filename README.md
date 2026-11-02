<img width="1672" height="941" alt="Изображение ChatGPT 29 сент  2026 г , 17_15_54-1" src="https://github.com/user-attachments/assets/0381af22-11cb-4714-8355-3721fa33dbac" />

# Snapmaker U1 Spool Tracker

> **1.1 public beta in preparation:** see the [beta release notes](RELEASE_NOTES_1.1.0-beta.1.md), [English beta quick start](MANUAL_1.1_BETA_EN.md), and [Russian beta guide](MANUAL_1.1_RU_DRAFT.md). The beta uses a separate inventory, is experimental, and is not yet a published release. The installation instructions below describe **v1.0.1**.

A small, local-first preflight utility for Snapmaker U1 and Snapmaker Orca / OrcaSlicer. It compares the per-tool filament requirement in G-code with four physical spool assignments: Slot 1 → T0 through Slot 4 → T3.

## What it does

- Keeps a local inventory of physical spools and remaining grams.
- Checks `; filament used [g] = ...` before G-code export. This preliminary check assumes a direct tool-to-slot mapping; the actual U1 mapping is verified only at print start. A provisional shortage opens a native Cancel Export / Proceed Anyway dialog.
- Cancelling returns a nonzero exit code. Proceed Anyway and a successful check return zero. The G-code is not modified.
- A missing or invalid per-tool usage line is an error and cancels export. The latest result, with one row per toolhead, is shown on the dashboard.
- In v1.0.1, export creates a planned job and does not itself deduct filament. The beta adds monitoring of actual print starts and estimate-based accounting; see the beta guides for conditions and limitations.
- A configurable reserve is added only to used toolheads for the preflight check; it is not deducted.

The 1.1 beta adds actual print-start checks, an optional experimental pause on risk, and accounting for supported completed or cancelled jobs. The printer can already be printing when the guard responds. Automatic replenishment across spools remains experimental and has not been physically validated. See the [beta release notes](RELEASE_NOTES_1.1.0-beta.1.md) for the full comparison and limitations.

## Install and use

Download v1.0.1 from [GitHub Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.0.1). On macOS, unpack `SnapmakerSpoolTracker-macOS.zip`, move `SnapmakerSpoolTracker.app` to `/Applications`, and open it; the unsigned app may require **Open** from the context menu. On Windows, put `SnapmakerSpoolTracker-Windows.exe` in a stable folder such as `C:\Tools\SnapmakerSpoolTracker` and run it to show the tray icon. The native Windows dashboard requires Microsoft Edge WebView2 Runtime.

Click the menu-bar/tray icon and choose **Configure Spools & Slots**. The native pywebview window updates print state, preflight results, and balances live. Closing it leaves the tray app running; reopen it from the menu. A second launch does not create another tray instance, but the tray command is the reliable way to reopen a window closed with X. Add real spools, set their initial weights, and assign the four slots. A fresh installation starts empty. The local `http://127.0.0.1:8765` page is for troubleshooting only.

The instructions in this section apply to v1.0.1. For the 1.1 beta, follow the [English beta quick start](MANUAL_1.1_BETA_EN.md) or [Russian beta guide](MANUAL_1.1_RU_DRAFT.md), including the separate beta data and backup instructions.

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
