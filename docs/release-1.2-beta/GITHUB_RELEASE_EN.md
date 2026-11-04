# GitHub Release draft — not published

Proposed title: **1.2 beta — automatic Snorca slice forecasts**
Proposed tag: `v1.2.0-beta` (not created by this documentation task).
Release type: **pre-release**. This is a local text draft; no GitHub draft release has been created.

Editorial note: after release assets exist, add their verified download links. Do not publish this header or editorial note.

---

**Windows GUI, real Snorca slicing on Windows and automatic window display on Windows have not yet been tested.** Windows CI tests and the packaged self-test passed; a separate desktop test is still needed.

## After slicing, see whether your filament is enough

Tracker 1.2 beta adds automatic observation of completed Snorca slice results. With Tracker running, a new completed result brings Overview forward with consumption, recorded spool balances, reserve-aware ✓ / ✕ indicators and a compact plate selector.

No manual G-code export or custom slicer build is required for this forecast. Slicing and reslicing do not deduct or reserve filament. The forecast feature does not send G-code or control printing.

## Packages

Both packages were built in CI from commit `83be812` and passed their packaged self-tests.

- `SnapmakerSpoolTracker-1.2-beta-macOS.zip` — macOS Apple Silicon / arm64; ad-hoc signed, not notarized.
- `SnapmakerSpoolTracker-1.2-beta-Windows.exe` — Windows x64; native dashboard requires WebView2.
- Corresponding `.sha256` checksum files.

## Data and limitations

- Separate, initially empty `SnapmakerSpoolTracker-Beta12` database; no automatic import or synchronization with the installed Tracker.
- Native backup import/export is available. Import replaces candidate data and saves a pre-import safety copy. A normal backup may enable printer monitoring; use `--isolated-root` with artificial data for offline testing.
- Assumed mapping: material 1→T0 … 4→T3, visibly labelled. It is not confirmation of the printer's actual job mapping.
- Forecast follows the latest completed slice project. It does not describe unsliced edits. The selector shows the forecast of one plate, not the total of all plates.
- Supported observation is based on Snorca 2.4.1 non-BBL temporary files. Other versions/layouts are not validated.
- Consumption is estimated and balances come from inventory records. A green check is not a guarantee of successful printing.

## What was checked

Real Snorca GUI slicing was exercised in the isolated macOS Lab. The integrated main application was checked in a Mac window using offline test files for multiple plates, repeated auto-show and shortage handling. Windows validation currently covers CI and packaged self-test only. Printer control on a physical U1 was not validated by this work.
