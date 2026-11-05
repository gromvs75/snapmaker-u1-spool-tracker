# Tracker 1.2.1 — preparation guide

**1.2.1 is not published yet. Windows GUI and real Snorca slicing on Windows remain unverified.** See the [1.2.1 release notes](../releases/1.2.1.md).

## The new workflow

1. Keep Tracker running in the menu bar/tray.
2. Check the spool assignments and remaining grams in Tracker.
3. Slice a model in Snapmaker Orca (Snorca). No manual G-code export, file selection, post-processing-script change, or custom slicer build is required for this forecast workflow.
4. A completed slice updates the icon and menu. On macOS the menu opens automatically; the dashboard stays hidden and there is no Dock icon. On Windows, open the tray menu yourself. Balance changes refresh the result without automatically opening the menu.
5. Click the menu forecast to open Overview for the latest completed plate. You can select another plate inside the window; this does not change the latest-slice status in the menu. Closing the window leaves Tracker running. Use Quit to stop it.

The menu shows the plate and timestamp: ✓ enough including reserve, ✕ shortage, neutral when the forecast is unavailable or a used spool is unassigned. Menu text supports EN/RU/DE/UK/ES.

A green ✓ means the estimated requirement plus reserve fits the recorded balance; a red ✕ means it does not. Unused heads have a neutral status. The head cards show consumption, balance, and either the estimated amount after printing or the shortage including reserve. Reserve is applied once per used spool; if several heads share a spool, their usage is combined.

**Slicing does not deduct or reserve filament.** Reslicing replaces the forecast for that plate; it does not record a printed job. The forecast feature does not upload G-code or start, stop, pause, or block a print. Existing print monitoring/accounting is a separate feature. While a print is running or paused, its head-card estimates take precedence; the slice summary remains separate.

## Prepared packages

macOS: `SnapmakerSpoolTracker-1.2.1-macOS.zip` (Apple Silicon arm64, ad-hoc signed, not notarized). Windows: `SnapmakerSpoolTracker-1.2.1-Windows.exe` (x64; WebView2 required). SHA256 and BUILD-INFO accompany prepared artifacts. These are not published downloads. The previous release is [1.2 beta](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v1.2.0-beta).

Keep packages separate from installed applications while reviewing. Use `--isolated-root` and artificial data for offline validation; ordinary launch is not isolated. Windows GUI remains unverified.

## Separate data and backup

1.2.1 keeps the 1.2 beta database and port for continuity. If that database does not exist, it starts empty. It does not automatically import older stable or Menu Test inventories:

- macOS: `~/Library/Application Support/SnapmakerSpoolTracker-Beta12/`
- Windows: `%LOCALAPPDATA%\SnapmakerSpoolTracker-Beta12\`
- Local dashboard: `http://127.0.0.1:8766` (native window recommended; native backup dialogs are not available in a normal browser).

To migrate deliberately, export a JSON backup from the old application's native window and save it outside either data directory. Import it from the new application's Settings. Import replaces the saved data and creates a pre-import safety copy. Verify all spools, T0–T3 assignments, balances and reserve afterward. No data is synchronized with older stable versions or Menu Test 1/2.

**A normal backup can contain enabled printer-monitor settings.** For testing without printer access, use isolated mode; it disables imported printer settings and blocks printer actions. Do not use a personal backup in the disposable test kit: it already supplies artificial inventory.

## Observer scope

The observer reads completed Snorca files under `<OS temporary directory>/snapmaker_orca_model`. A custom backup root can be passed as `--slice-root PATH`. If the root does not exist, Tracker waits for it; it does not create or reconfigure Snorca's folders. Parsing is based on the Snorca 2.4.1 non-BBL layout. Other slicers and versions are not validated.

The forecast uses the project with the most recently completed slice. Opening or editing another project without completing a slice does not switch it. Unfinished files do not create a new forecast; the last completed result remains visible with its timestamp. After temporary-file cleanup, a new completed slice may be needed.

Material mapping is **assumed: material 1→T0, 2→T1, 3→T2, 4→T3**. This is labelled in Overview and is not confirmation of the printer's eventual mapping. Consumption is a slicer estimate, and balances are recorded values, not live measurements. A green check is not a guarantee that a print will complete.

## Offline developer/test mode

Create a fresh directory containing `ISOLATED_TRACKER_TEST` with exactly `offline-only` and a trailing newline, then launch:

```text
SnapmakerSpoolTracker --isolated-root PATH
```

On macOS, use the binary inside `Contents/MacOS/` of the candidate `.app`; on Windows, use the candidate `.exe`. This mode uses only the explicit test inventory and an ephemeral loopback port. Printer-monitor threads do not start; printer, sender and accounting-control routes are blocked. The default watched directory is `PATH/slices`; `--slice-root` may override it only with a path inside the test root. The native webview storage is also kept in that test root.

For actual Snorca slicing, both applications must share the isolated temporary directory; the [Windows Sandbox kit](../../dev/windows_slice_check/README_RU.md) prepares this arrangement. No real U1 or host profiles are needed. That kit is prepared but has not been executed on Windows here.

## Reporting a result

Include OS/architecture, Tracker and Snorca versions, whether the window was hidden or minimized, which plate was sliced, whether the forecast changed, and whether the window actually appeared. State whether you used artificial inventory and confirm that slicing alone did not alter balances. Remove personal paths, filenames, printer addresses and backup contents before sharing logs. Screenshots of the result are more useful than a claim that the executable merely launched.
