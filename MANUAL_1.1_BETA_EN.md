# Snapmaker U1 Spool Tracker 1.1 beta — quick start

This is a public testing release. Filament amounts are estimates, not measurements. Actual U1 automatic replenishment and some interruption scenarios have not been validated. See [release notes](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.1.0-beta.1) for limitations.

## Install safely

1. Finish any active print. In v1.0.1, open **Backup & Restore → Export Backup**, save the backup outside the app folder, and fully quit the old tracker from the menu-bar/tray menu.
2. Download and start the beta for your OS. Keep the old app until you have checked the migration. On macOS, unpack and move `SnapmakerSpoolTracker-1.1.0-beta.1.app` to Applications; it is not notarized and may require the system's context-menu Open action. On Windows, run `SnapmakerSpoolTracker-1.1.0-beta.1-Windows.exe` from a stable folder; the dashboard requires Edge WebView2 Runtime. Windows automated tests and the packaged self-test passed on GitHub Actions, but the interactive dashboard and connection to a physical U1 have not yet been tested on Windows.
3. In the beta, open **Settings → Backup & Restore → Import Backup** and select the exported file. Import replaces existing beta data and resets the guard to warning mode; do not import an old backup over beta data you wish to keep.
4. Check spools, balances, T0–T3 assignments and the printer connection. Once verified, you may remove the v1.0.1 app and keep the backup somewhere safe. Remove only the app; cleaning utilities may also remove its data. Update any Orca post-processing path to point to the beta (see below). Include `1.1.0-beta.1` when reporting feedback.

The beta maintains a separate `SnapmakerSpoolTracker-PublicBeta11` data folder. It may copy v1.0.1 spools and settings automatically on first launch, but the explicit backup import above is the recommended migration. Plans and history are not copied by the automatic first-run process. The two inventories do not sync, and importing beta data back into v1.0.1 has not been verified. Previous developer beta data is not copied automatically.

## Configure

On **Spools**, add or check the spools, their remaining weight and physical T0–T3 assignments; save assignments. Color is optional. On **Settings**, enter the U1 address and Moonraker port (normally `7125`), test the connection, enable accounting and save. The reserve is used for preflight checks, not deducted.

Keep Tracker running in the tray/menu bar, the computer awake and the printer connected. Closing the dashboard does not quit the tray app. The print-start check runs after the printer starts; warning mode does not stop printing, and pause-on-risk is experimental. Observe the printer directly if a pause command is uncertain.

Successful prints may be booked using a G-code estimate; cancelled prints may be booked using observed motion when supported. If the system cannot establish a reliable allocation, the job is shown as unaccounted and balances remain unchanged. Auto-replenishment is experimental and has not been tested with real spool runout. Do not change assignments or the used spool's balance mid-print while testing accounting.

## Optional: slicer export check

In Snapmaker Orca / OrcaSlicer, add the beta executable under **Print Settings → Others → Post-processing scripts**. Examples, depending on where you installed the app:

```text
/Applications/SnapmakerSpoolTracker-1.1.0-beta.1.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker-1.1.0-beta.1-Windows.exe;
```

Quote executable paths containing spaces, leaving the semicolon outside the quotes. Save the process preset and test a small slice. An old post-processing command targeting v1.0.1 still invokes that version. This is an export check, not a Send/Print plugin.

## Feedback

Open an issue at https://github.com/gromvs75/snapmaker-u1-spool-tracker/issues with OS, Tracker and U1 firmware versions, steps, expected versus actual result, print start method and whether the print paused, was cancelled or replenished. Screenshots or logs are optional; remove sensitive filenames, network addresses and other private data before sending.
