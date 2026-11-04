# Snapmaker Forum — final text, not posted

**Suggested title for a new topic:** U1 Spool Tracker 1.2 beta candidate — automatic filament forecast after Snorca slicing

**For an existing Tracker topic:** use the body below as an update, without changing the existing topic title.

I'm preparing the 1.2 beta candidate of U1 Spool Tracker. The new workflow checks whether your recorded spool balances are sufficient after slicing in Snapmaker Orca (Snorca), before you decide to print.

**Windows GUI, real Snorca slicing on Windows and automatic window display on Windows have not yet been tested.** A Windows executable is available as a CI artifact, but it still needs a separate desktop test.

With Tracker running in the menu bar/tray, complete a slice in Snorca. Tracker detects the result and automatically shows Overview with the estimated usage and green ✓ / red ✕ indicators beside the heads. For multiple completed plates, select the plate to check. There is no manual G-code export, file selection, or modified slicer involved in this forecast workflow.

For example, if a plate needs 80 g, the assigned spool has 77.5 g, and the configured reserve is 5 g, Tracker shows a shortage of 7.5 g including reserve. This is an estimate based on the slicer and the recorded balance. **Slicing does not deduct or reserve filament.** Reslicing updates the forecast, and Tracker's forecast feature does not upload or start a print.

### Current validation status

- Real slicing in Snorca GUI, reslicing and multiple plates were tested in an isolated macOS Lab.
- The integrated main application's Mac window was checked with offline test files, including plate selection, repeated auto-show and shortage indicators.
- The macOS arm64 and Windows x64 candidates were built from the same commit and passed CI tests and packaged self-tests. The Mac package also passed signature verification.
- The Windows offline test kit is prepared but has not been run here; successful CI is not a substitute for the GUI check described above.

### Before trying the candidate

Packages target macOS Apple Silicon (arm64) and Windows x64. The Mac app is ad-hoc signed, not notarized; the Windows window requires WebView2.

The beta uses an empty, separate inventory and does not automatically import or synchronize your existing Tracker data. Backup import is available, but a normal backup may contain enabled printer-monitor settings. Use the dedicated isolated test mode with artificial inventory for offline testing. Keep the candidate separate from your installed Tracker.

Material mapping for the slice forecast is currently **assumed: 1→T0 … 4→T3**, and is labelled accordingly. The forecast follows the most recently completed slice project; simply opening or editing a different project does not replace it. File-layout support is based on Snorca 2.4.1, and a green check is not a guarantee that a print will complete.

### Looking for a Windows tester

I don't have a Windows computer, so I'm looking for someone to help test the interface and automatic forecast display after slicing in Snorca. The Windows build passed automated tests, but this workflow has not yet been tested on a Windows desktop.

I've prepared a test kit for a separate, isolated environment with artificial spool data. No real U1 or personal Tracker/Snorca settings are needed. If you'd like to help, please reply in this thread and I'll provide the build and a short setup guide.

The short checklist is:

1. Hide Tracker, press Slice in Snorca, and confirm that the forecast window actually appears.
2. Change the model or layer height, slice again, and check that the estimate updates.
3. Slice two plates and check their separate forecasts.
4. Verify that slicing alone leaves spool balances unchanged.

Please include your Windows and Snorca versions and describe which step worked or failed. A real printer connection is not needed. This remains a candidate; a public 1.2 release has not been published.

[Project](https://github.com/gromvs75/snapmaker-u1-spool-tracker) · [Candidate source branch](https://github.com/gromvs75/snapmaker-u1-spool-tracker/tree/v1.2-beta-integration-build)
