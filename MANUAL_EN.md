# Snapmaker U1 Spool Tracker — user manual

## Installation and first launch

Download v1.0.1 from [GitHub Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.0.1). On macOS, unpack `SnapmakerSpoolTracker-macOS.zip`, drag `SnapmakerSpoolTracker.app` to `/Applications`, and open it. An unsigned build may require **Open** from the context menu. On Windows, keep `SnapmakerSpoolTracker-Windows.exe` in a stable folder; the native dashboard requires Microsoft Edge WebView2 Runtime. No account or cloud service is needed.

Click the menu-bar/tray icon → **Configure Spools & Slots** to open the native window. It updates itself. X hides the window but leaves the tray app running; use the tray command to reopen it. Another launch does not create a second tray instance and can restore a minimized window, but is not the reliable way to reopen a window hidden with X.

## Spools, slots, and reserve

On first launch, add each physical spool with a name, material, and measured remaining grams. Assign Slot 1 → T0, Slot 2 → T1, Slot 3 → T2, Slot 4 → T3 and save. Deleting a spool clears its slot. Enter initial weight once; correct it after weighing or when a job needs manual review. **Safety reserve** starts at 0 g and is added to each used toolhead's preflight requirement only. It is never deducted.

## U1 / Moonraker connection

Under **U1 printer monitor**, enter host/IP (default `U1.local`) and port (default `7125`), click **Test Connection**, enable automatic accounting, and save. The dashboard shows connection, printer state, and filename. Keep the tray app running. The monitor uses stock local Moonraker, needs no firmware change, and resumes from history after a disconnect or app restart. Preflight works while offline. Deleted/changed remote files or ambiguous matching plans require manual review and leave inventory unchanged.

## Snapmaker Orca / OrcaSlicer setup

In **Print Settings → Others → Post-processing scripts**, add the executable path with a trailing semicolon; save the process preset:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker-Windows.exe;
```

Use your actual Windows path and quote paths containing spaces. For macOS source use, install dependencies and provide the absolute path to `run_hook.sh;`.

## Export, print, and accounting

On export, the hook reads T0–T3 filament usage and checks assigned spools. Enough filament allows export. For a shortage or unassigned used toolhead, choose **Cancel Export** (Orca exit code 1) or **Proceed Anyway**. Unreadable G-code or invalid/missing usage metadata fails closed. G-code is not changed.

An allowed export creates **planned**: filename, SHA-256, byte size, T0–T3 grams, and spool IDs captured at preflight. Exports and uploads never deduct. A matching actual print becomes **active**; a successful **completed/committed** job deducts the estimate from captured spools once. **Cancelled** and **error** jobs do not deduct the full planned amount. **Review** means no automatic debit pending inspection. Matching uses filename, hash, size, printer identity, and preflight time; a persistent run identity prevents duplicate debits after reconnect. Status and balances update without manual refresh. Weigh and correct a spool if actual use differs from the slicer estimate. Material mismatch and physical feed failures are not detected.

## Export and import a portable backup

In the native window, use **Backup & Restore → Export Backup**. The native Save dialog suggests `SnapmakerSpoolTracker-backup-YYYY-MM-DD.json`. Save outside the app data directory, for example in Documents, Desktop, or an external drive. The UTF-8 JSON contains language, reserve, spools, slots, printer settings, last preflight, planned jobs, and accounting runs. It excludes the live connection state, logs, lock files, binaries, and internal corruption backups. Export does not change the database.

To restore, click **Import Backup**, confirm replacement of current inventory, settings, and accounting history, and select an exported backup in the native Open dialog. The whole file is validated before replacement. A copy of the old database is saved to `backups/pre-import-*.json`; the new database is written atomically. Dashboard and tray update without restart. The monitor starts disconnected if enabled, or disabled otherwise, until the next poll. Invalid, partial, oversized, or unsupported backups are rejected. Raw legacy `spools_u1.json` is not accepted by Import Backup. Backup buttons are unavailable in the troubleshooting browser page.

## Safe upgrade and uninstall

On macOS: (1) Quit the tracker from its menu. (2) Export a portable backup outside Application Support. (3) Download/unpack the new `.app`. (4) Drag it into `/Applications` and choose **Replace**. Do not remove the old app with AppCleaner or CleanMyMac first if preserving data: such tools may delete `~/Library/Application Support/SnapmakerSpoolTracker/` and its internal `backups/`. A portable backup saved elsewhere survives. On Windows, export before uninstalling or moving installations.

For a full uninstall, quit and remove the app/executable. Delete the data folder only if you intentionally want to erase inventory and accounting history.

## Data locations and troubleshooting

- macOS: `~/Library/Application Support/SnapmakerSpoolTracker/`
- Windows: `%LOCALAPPDATA%\SnapmakerSpoolTracker\`
- Linux source use: `${XDG_DATA_HOME:-~/.local/share}/SnapmakerSpoolTracker/`

The folder holds `spools_u1.json`, the lock file, `tracker.log`, and internal `backups/`. A valid old database beside a previous executable or script can migrate on first launch; the original remains. A corrupt active database is preserved and copied, not reset. `http://127.0.0.1:8765` is only a troubleshooting fallback. Check host/port and `tracker.log` if the monitor stays disconnected. Test the hook with a small real slice and deliberate shortage before relying on it. Physical U1 hardware has not yet been validated in this test cycle.
