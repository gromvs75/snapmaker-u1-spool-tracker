# Reddit draft — not posted

**Title:** Snapmaker U1 Spool Tracker 1.2 beta: filament forecasts after slicing in Snorca — Windows testers wanted

I'm preparing 1.2 beta of Snapmaker U1 Spool Tracker. The main addition is a filament forecast that appears after slicing in Snapmaker Orca (Snorca).

**Windows GUI and real Snorca slicing on Windows have not been tested yet, including automatic window display.** The Windows x64 executable passed CI tests and its packaged self-test; a desktop test is still needed.

Keep Tracker running in the tray/menu bar, slice your model, and it detects the completed result and brings Overview forward. It compares the estimated consumption with your recorded spool balances and reserve. Used heads get a green ✓ or red ✕; multi-plate projects have a compact plate selector.

No manual G-code export, file picking, post-processing-script change, or custom slicer build is needed for this forecast workflow. Slicing and reslicing do **not** deduct filament, and the forecast does not send or start a print.

Current limits:

- Material mapping is currently assumed: 1→T0 … 4→T3. Tracker labels that assumption; it is not confirmation of the printer's eventual mapping.
- The forecast refers to the latest completed slice, not an edited model that hasn't been sliced again.
- Observation is based on Snorca 2.4.1 temporary results; other slicers and versions have not been validated.
- Beta starts with a separate empty inventory. For offline testing, use isolated mode with artificial spools; a normal backup import may enable printer monitoring.

Real Snorca slicing was tested in the isolated Mac Lab; the integrated main application's window and auto-show were checked with offline test files on Mac. A macOS Apple Silicon (arm64) candidate and a Windows x64 candidate have been built. This is still a candidate, not a published 1.2 release.

I'd welcome a Windows tester who already has a disposable offline Windows environment. The useful checks are Slice → auto-show, reslicing → updated forecast, two plates → separate forecasts, and unchanged spool balances. No real U1 or personal printer profiles are needed.

[Project](https://github.com/gromvs75/snapmaker-u1-spool-tracker) · [Candidate source branch](https://github.com/gromvs75/snapmaker-u1-spool-tracker/tree/codex/v1.2-beta-integration-build)
