# 1.2.0-beta.1 — integration candidate

This is a test candidate, not a published release. macOS and Windows packages are built from the same source snapshot.

## Added

- Automatic observation of completed Snorca slice files, compact forecast in Overview, plate selection, and automatic window reveal.
- Inventory-backed forecast with the configured reserve, without debiting or reserving filament.
- Forecast captions in Russian, German and English (English fallback for other languages).
- Active printing keeps its existing head-card estimates; the slice forecast has its own summary.
- Native backup import/export remains available in the main application.

## Data and operation

Beta uses a separate `SnapmakerSpoolTracker-Beta12` data directory next to the usual app directory. It starts empty and does not automatically import the installed Tracker database. To migrate, explicitly export/import a backup. An imported normal backup may enable its printer monitor; use the isolated mode for offline tests.

The observer reads `<OS temporary directory>/snapmaker_orca_model`. It waits if the directory does not exist yet. Use `--slice-root PATH` for a custom Snorca backup root. No Snorca settings are modified. File layout support is based on Snorca 2.4.1 non-BBL results; Windows GUI slicing is not yet validated.

`--isolated-root PATH` requires `PATH/ISOLATED_TRACKER_TEST` containing `offline-only` followed by a newline. It uses only `PATH/inventory`, `PATH/slices` and a random loopback port. Printer monitors are not started, printer/sender/accounting HTTP actions are denied, and imported printer settings are disabled. It never falls back to the normal data directory or the real Snorca directory. Optional `--slice-root` must stay inside the test root.

## Limitations before release

- Material mapping is assumed: 1→T0 … 4→T3. This is visibly labelled, not confirmed by the printer.
- Forecast follows the project with the latest completed slice, not the currently focused or edited GUI project.
- The observer does not start/stop/pause prints. Existing printer-monitor features are separate.
- macOS local builds are ad-hoc signed, not notarized. Check package architecture before use.
- Windows requires a functioning WebView2 runtime. CI packaging/self-test does not substitute for Windows GUI validation.
- Temporary slice files may disappear after an OS cleanup. Inventory is persistent in the app data directory.

## Validation

Offline synthetic partial files, reslicing, two plates, repeat auto-show, inventory preservation, forecast/active-print separation, backup logic, and package smoke test. Final platform-specific results and checksums accompany the artifacts.
