# Snapmaker U1 Spool Tracker — user manual

## 1. Install

Download a published macOS or Windows build from the project's Releases page when v1.0.1 is available. On Mac, move `SnapmakerSpoolTracker.app` to `/Applications` and open it. If macOS blocks the unsigned app, use the standard context-menu **Open** action. On Windows, extract `SnapmakerSpoolTracker.exe` into a stable folder and run it. The app appears in the menu bar or system tray. Starting it a second time opens the existing dashboard.

## 2. Set up inventory

Open **Configure Spools & Slots** from the tray, or visit `http://127.0.0.1:8765`. The first launch contains no spools or slot assignments. Add each physical spool with a name, material and actual remaining grams. Assign Slot 1 to T0, Slot 2 to T1, Slot 3 to T2 and Slot 4 to T3. Save the assignments. Deleting a spool clears its assignment. Edit remaining grams after a **real print** or when you weigh a spool.

The **Safety reserve** is added to each used toolhead's requirement for the preflight comparison. It is not deducted from inventory. It starts at 0 g.

## 3. Connect Snapmaker Orca / OrcaSlicer

In **Print Settings → Others → Post-processing scripts**, enter the executable path followed by a semicolon and save the process preset:

```text
/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
```

```text
C:\Tools\SnapmakerSpoolTracker\SnapmakerSpoolTracker.exe;
```

Replace the Windows path with the actual location. Quote paths containing spaces. If running from source on Mac, use the absolute path to `run_hook.sh;` after installing dependencies in `venv`.

## 4. Export and review

When Orca calls the script, it checks the G-code's per-tool filament usage against the assigned spools. If all used toolheads have enough material, export continues without a popup. The dashboard shows the latest result for T0–T3, including spool, required grams, remaining grams, and status.

If a used toolhead has no spool or insufficient material, choose **Cancel Export** to stop or **Proceed Anyway** to continue knowingly. If the G-code is unreadable or lacks valid per-tool usage metadata, export fails closed and shows an error. The app never edits or removes the G-code.

**Export does not consume filament.** Re-exporting five times leaves the inventory unchanged. Update the remaining weight after a real print.

## 5. Data and troubleshooting

macOS data: `~/Library/Application Support/SnapmakerSpoolTracker/`
Windows data: `%LOCALAPPDATA%\SnapmakerSpoolTracker\`

An existing valid `spools_u1.json` beside the old app or script is copied into the new data directory on first launch. The old file remains. If the database is corrupt, the app keeps it, makes a timestamped copy in `backups/`, and reports the error. `tracker.log` in the same directory helps diagnosis. Restore a good backup or contact the maintainer; the app will not silently replace the inventory.

Test with a small actual slice and deliberate shortage before relying on the hook for a long print. The tracker checks inventory estimates; it cannot detect physical tangles, failed feeding, or material mismatch.
