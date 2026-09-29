# Local U1 / Moonraker simulator

This development tool serves only the four stock Moonraker endpoints used by
SnapmakerSpoolTracker. It binds to `127.0.0.1` and uses port `7126`, leaving the
real U1's default `7125` alone. It requires only Python's standard library.
The app builds package `spool_tracker.py`; this simulator and `dev/` fixtures are not included in packaged builds. Simulator success does not prove compatibility with physical U1 firmware.

Start it from the repository root:

```sh
python dev/mock_u1.py
```

Open the simulator control page at <http://127.0.0.1:7126>. Open the tracker's native dashboard through its menu-bar/tray **Configure Spools & Slots** command. In its printer settings, use
host `127.0.0.1`, port `7126`, enable automatic accounting, save, and click
**Test Connection**. The simulator saves its selected file, print state, and
history in `dev/.mock_u1_state.json`; the file is ignored by Git. Stop the
server with Ctrl+C or **Disconnect / Stop Server**, then restart it to test
reconnection. Each print gets a new `job_id`; clicking **Complete Print** again
keeps the same completed job.

## Complete macOS manual test

Use a separate test inventory. A real Orca export and its post-processing hook
must create a plan in the same installed tracker data directory that its menu
app uses. The bundled sample files are metadata fixtures, not printable models.

1. Start the simulator, then launch the installed `SnapmakerSpoolTracker.app`.
2. Create four test spools with 1000 g each and assign them to T0–T3.
3. Configure the monitor for `127.0.0.1:7126`; test the connection.
4. Export G-code from Snapmaker Orca with the tracker's real post-processing
   hook (the exact Orca command is in the root README). Alternatively, from
   the repository root invoke the **installed app's** hook on a sample:

   ```sh
   /Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker "$(pwd)/dev/sample_gcodes/four_tool.gcode"
   ```

   Keep the exported G-code file available for the simulator.
5. Confirm the native dashboard updates to **planned** without manual reload and the export did not change inventory.
   Repeating the export must still cause no debit.
6. In the simulator, enter the **full local path** to those exact G-code bytes.
   If Orca's planned output name differs from that path's basename, fill in
   **Printer filename** with the planned filename shown in the tracker. Select
   the file. The simulator serves its real bytes for hash verification.
7. Click **Start Print**. After the next monitor poll (up to 10 seconds), the
   native dashboard should show **active** without reload and inventory unchanged.
8. Click **Complete Print**. After the next poll, check that each used spool
   lost only its planned grams. Click Complete again and restart both the app
   and simulator; the same job must not debit again.
9. Select and start another planned file, then **Cancel Print**; repeat with
   **Error Print**. Neither should debit the planned total.
10. Select `unrelated.gcode`, start and complete it. A plan for another file
    must not debit. Also try a different local file with the same printer
    filename but different bytes; its hash must prevent a match.
11. For a new four-tool plan, change the tracker slot assignments after
    preflight. Completion must still debit the four spool IDs saved in the plan.
12. While the simulator is stopped, verify the tracker shows disconnected and
    leaves inventory untouched. Restart the simulator and confirm reconnect.
13. Export a portable backup from the native dashboard to a location outside
    the tracker data directory. Import it after changing test inventory and
    verify the restored data and `backups/pre-import-*.json`. Native dialogs
    are unavailable in the troubleshooting browser page.

The simulator accepts a path to a local `.gcode` or Orca `.gcode.pp` file.
For `.gcode.pp`, the default printer filename drops `.pp`, matching the
tracker's planned filename. **Do not send the synthetic fixtures to a physical printer.** The
control page and Moonraker subset have no login because they are local test
tools; never expose the port through a proxy or port-forward.
