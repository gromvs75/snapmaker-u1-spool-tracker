# Snapmaker U1 Spool Tracker 1.1.0-beta.1 — public beta draft

**Pre-release for feedback.** This beta introduces print-start checks and broader automatic accounting for Snapmaker U1, but has not been validated across all printer, firmware, network, material and auto-replenishment scenarios. It does not guarantee prevention of runout or accurate physical weight. Keep v1.0.1 available and export a backup before trying the beta.

## What changed since v1.0.1

- The U1 monitor can inspect the G-code of a job that has actually started, including a job started from the printer screen. The printer may already have begun preparing or printing by the time the check is available. Export post-processing remains a separate optional path; this is not an Orca Send/Print plugin.
- Logical G-code tools are mapped to the physical U1 toolheads reported for the active job. The overview displays assigned spools, estimated requirements and the currently selected toolhead when available.
- For supported, sufficiently observed prints, the beta can debit an estimated amount after success. A supported cancelled job can also be accounted from observed partial motion. Estimates are not measured weight; purge, loading, slip and interrupted monitoring can differ from estimates.
- Printer-side automatic replenishment is experimental: the printer controls switching. Allocation across spools is **not physically validated**. If the evidence is insufficient, Tracker leaves the job unaccounted and does not guess a deduction. The lack of an RFID tag does not by itself identify or prevent selection of a spool; untagged spool identity follows the user's assignment.
- The print-start guard provides warning mode and an experimental pause-on-risk mode. The pause can occur after the printer has started; a real U1 pause/resume was observed in one scenario, not every firmware or error case.
- Updated overview, spool colors, toolhead assignment, history and settings. The macOS menu includes small toolhead icons; other systems use text labels.
- Improved selected edge cases around pause/resume, repeated observations, cancellation, and delayed network frames. The latest network fix has not yet been validated during a long physical print. A sleep, restart or actual connection loss can still leave jobs unaccounted.

## Installation and data

Back up v1.0.1 using its Export Backup command, wait for the current print to finish, and quit it before starting the beta. The beta seeds a separate `SnapmakerSpoolTracker-PublicBeta11` data directory from the normal v1.0.1 directory on first run when available. Spools and settings are copied; job history, plans and transient state are not. Afterwards the two inventories are independent. If the normal directory is missing, start empty or import an existing portable backup. Internal developer beta data is not automatically copied. Do not run both versions at once. Importing a backup replaces the target beta data and resets the guard to warning mode. Backward import from beta into v1.0.1 is not verified.

The macOS package is currently built locally for Apple silicon and is not notarized; Intel macOS support is unverified. The Windows package was built on a GitHub Actions Windows runner, where automated tests and the packaged command-line self-test passed. Edge WebView2 Runtime is needed. The interactive Windows dashboard and a connection to a physical U1 have not yet been tested on Windows.

## Test and report

Run the tracker in the menu bar/tray with the printer monitor enabled, keep the computer awake and connected, and confirm physical spools are assigned correctly. Start with a small print, then compare the predicted and booked amounts. For a cancellation, the full slicer estimate should not be deducted; a partial motion estimate is possible only when sufficiently supported. An unaccounted job means balances were not changed.

Please report the Tracker version, OS and U1 firmware, how the print was started, whether it completed, paused, was cancelled or auto-replenished, and expected versus actual result. Screenshots and logs are optional: review them for private filenames, addresses and other sensitive information before sharing. Report issues at https://github.com/gromvs75/snapmaker-u1-spool-tracker/issues .
