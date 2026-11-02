# Snapmaker U1 Spool Tracker 1.1 beta — quick start

This is a public testing release. Filament amounts are estimates, not measurements. Actual U1 automatic replenishment and some interruption scenarios have not been validated. See [release notes](RELEASE_NOTES_1.1.0-beta.1.md) for limitations.

## Install safely

1. Finish any active print. Export a portable backup from v1.0.1 to a separate folder, then fully quit the old tracker from its menu-bar/tray menu.
2. Open the beta. On macOS, unpack and move `SnapmakerSpoolTracker-1.1.0-beta.1.app` to Applications; it is not notarized and may require the system's context-menu Open action. On Windows, run `SnapmakerSpoolTracker-1.1.0-beta.1-Windows.exe` from a stable folder; the dashboard requires Edge WebView2 Runtime. Distribution is subject to the platform checks in the release notes.
3. The beta maintains its own `SnapmakerSpoolTracker-PublicBeta11` folder. On its first run it copies spools and settings from the standard v1.0.1 data folder when present, without modifying the original. Plans and history are not copied. If the normal data folder is absent, start empty or import your exported backup. Previous developer beta data is not copied automatically.
4. The two versions then have independent inventories. Do not run both at once. Importing a backup replaces beta data and resets printer guard to warning mode. Importing beta data back into v1.0.1 has not been verified.

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
