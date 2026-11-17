# Snorca bed numbers in Tracker 2.0

Available in candidate **2.0.0rc16 and later**. Verified with Snapmaker Orca
2.4.1 on macOS; the Windows build of this change has not been verified.

**Reliable bed numbering requires one setup step in every Snorca printer
preset you use, followed by a new slice.** Tracker does not install this
setting automatically. Without it, usage forecasts may still work, but the
bed number is not guaranteed to be available.

## Set up the printer preset

1. Open the selected printer's settings in Snorca → **Machine G-code**.
2. Add this as the first line of **Machine start G-code**, before the existing
   code. This is not the process preset's post-processing scripts field:

   ```gcode
   ; TRACKER_BED_V1 = {plate_number}
   ```

3. Keep all existing start G-code unchanged. Keep the semicolon and braces;
   do not replace the variable with a literal number. Add the line only once.
4. Click the **save/disk icon** and save a separate user preset, for example
   **Snapmaker U1 · Tracker**.
5. **Select that saved printer preset in the current project.** Editing a
   preset does not help if a different preset is used for slicing.
6. Reopen its start G-code to confirm the line was saved, then slice the
   required beds again.

Snorca expands the variable to `01`, `02`, `03`, etc. during slicing.
Tracker reads the number from the completed G-code itself. Slicing only bed 3
keeps its number as 3, even if no other bed has been sliced. No export, upload,
printer connection or firmware patch is needed. The added line is a comment,
not a printer command.

## Check the result

In Tracker rc16 or later, open **Overview → Slice forecast** after slicing.
The bed number should match Snorca. Try slicing bed 2 alone to verify it
remains bed 2.

If Tracker shows an unknown bed:

- Check the printer preset selected in this project and the saved comment.
  Loading another 3MF, changing presets or resetting settings may restore
  a preset without the comment.
- Re-slice after saving and selecting the preset. Check the forecast's
  source and time to ensure you are looking at that new slice.
- For diagnosis only, export the G-code and find a standalone line such as
  `; TRACKER_BED_V1 = 02` near the start of the executable block. A saved
  `machine_start_gcode` configuration value containing `{plate_number}` is
  not sufficient: the executable block must contain the expanded number.
- No expanded line means the comment was not included in that slice's
  settings. Duplicate lines, an unexpanded variable or malformed values
  are rejected. Correct the preset and re-slice; do not manually number
  the finished G-code.
- If the expanded line is correct but the number is still unknown, retain
  the G-code, Tracker version and forecast source details for diagnosis.

## Scope and prepared projects

The number describes the bed **when this file was sliced**, not the current
selection in Snorca. Re-slice after reordering beds. Existing G-code does not
gain a number retroactively. Without the comment, Tracker can use explicit
fresh project references when available; otherwise it shows an unknown bed.

A prepared 3MF copy may already contain the comment. Open it as a project
with its settings, then re-slice. Check the comment if you switch printer
presets. Developers can create a separate copy without changing the input:

```sh
python dev/prepare_bed_marker_project.py input.3mf output-with-bed-marker.3mf
```

The comment does not identify a physical toolhead, confirm RFID/UID or allow
filament deductions. Usage accounting, Spoolman and RFID require their own
setup. Changing spool assignments or manually deducting usage will not fix
an unknown bed number.

[Русская инструкция](snorca-bed-identity-ru.md)
