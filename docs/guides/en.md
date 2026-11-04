# Tracker 1.2 beta — candidate guide

**Status: integration candidate; no 1.2 beta GitHub Release has been published. Windows GUI and real Snorca slicing on Windows have not been validated.** Windows CI tests, packaging and the executable's built-in self-test passed. They do not demonstrate that window activation or slicing integration works on a user's Windows desktop.

See the [release notes](../releases/1.2-beta.md) for changes, package details and the validation record.

## The new workflow

1. Keep Tracker running in the menu bar/tray.
2. Check the spool assignments and remaining grams in Tracker.
3. Slice a model in Snapmaker Orca (Snorca). No manual G-code export, file selection, post-processing-script change, or custom slicer build is required for this forecast workflow.
4. When Tracker detects a completed result, it brings Overview forward and shows the estimated consumption and whether the assigned spools have enough filament, including the configured reserve.
5. If the project has several completed plates, select the plate whose forecast you want to see. The forecast is for that plate, not a total for all plates.

A green ✓ means the estimated requirement plus reserve fits the recorded balance; a red ✕ means it does not. Unused heads have a neutral status. The head cards show consumption, balance, and either the estimated amount after printing or the shortage including reserve. Reserve is applied once per used spool; if several heads share a spool, their usage is combined.

**Slicing does not deduct or reserve filament.** Reslicing replaces the forecast for that plate; it does not record a printed job. The forecast feature does not upload G-code or start, stop, pause, or block a print. Existing print monitoring/accounting is a separate feature. While a print is running or paused, its head-card estimates take precedence; the slice summary remains separate.

## Candidate packages

| Platform | Package | Validation |
|---|---|---|
| macOS Apple Silicon (arm64) | `SnapmakerSpoolTracker-1.2-beta-macOS.zip` | CI tests, packaged self-test and signature checks passed. Earlier integrated application tested offline in a native Mac window; final packages rechecked through self-test |
| Windows x64 | `SnapmakerSpoolTracker-1.2-beta-Windows.exe` | CI and packaged self-test passed; **Windows GUI and real Snorca slicing unverified** |

Current build runs are the [macOS CI run](https://github.com/gromvs75/snapmaker-u1-spool-tracker/actions/runs/41889187825) and [Windows CI run](https://github.com/gromvs75/snapmaker-u1-spool-tracker/actions/runs/41889187834); both passed at commit `83be812`. The current Mac CI package is `SnapmakerSpoolTracker-1.2-beta-macOS.zip`. Actions downloads may require GitHub sign-in and expire. These are not permanent release download links. An Intel Mac package is not provided by this candidate. macOS signing is ad-hoc, without notarization. Windows needs a functioning Microsoft Edge WebView2 runtime; this executable is not an installer for that runtime.

Keep the candidate in a separate folder; do not replace the installed Tracker for an offline test. For the fully isolated path, use the [Windows test-kit instructions](../../dev/windows_slice_check/README_RU.md) or the CLI instructions below. Ordinary launch is not equivalent to offline isolation.

## Separate data and backup

The candidate starts with an empty, separate database. It does not automatically import or synchronize the installed Tracker inventory:

- macOS: `~/Library/Application Support/SnapmakerSpoolTracker-Beta12/`
- Windows: `%LOCALAPPDATA%\SnapmakerSpoolTracker-Beta12\`
- Local dashboard: `http://127.0.0.1:8766` (native window recommended; native backup dialogs are not available in a normal browser).

To migrate deliberately, export a JSON backup from the old application's native window and save it outside either data directory. Import it from the candidate's Settings. Import replaces the candidate's saved data and creates a pre-import safety copy. Verify all spools, T0–T3 assignments, balances and reserve afterward. Changes in beta do not sync back to the installed version.

**A normal backup can contain enabled printer-monitor settings.** For testing without printer access, use isolated mode; it disables imported printer settings and blocks printer actions. Do not use a personal backup in the disposable test kit: it already supplies artificial inventory.

## Observer scope

The observer reads completed Snorca files under `<OS temporary directory>/snapmaker_orca_model`. A custom backup root can be passed as `--slice-root PATH`. If the root does not exist, Tracker waits for it; it does not create or reconfigure Snorca's folders. Parsing is based on the Snorca 2.4.1 non-BBL layout. Other slicers and versions are not validated by this candidate.

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
